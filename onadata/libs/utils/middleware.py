# coding: utf-8
from typing import Union

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotAllowed
from django.middleware.locale import LocaleMiddleware
from django.template import loader
from django.template.loader import get_template
from django.utils.deprecation import MiddlewareMixin
from django.utils.translation import gettext as t
from django.utils.translation.trans_real import parse_accept_lang_header
from kobo_service_account.models import ServiceAccountUser

from onadata.libs.http import JsonResponseForbidden, XMLResponseForbidden

# Define views (and viewsets) below.
# Viewset actions must specify (as a list) for each method.
# Legacy Django views do not need a list of actions, it can be empty.
# E.g. : Allow exports
#   > 'export_list': { 'GET': [] }
#   > 'create_export': { 'POST': [] }
ALLOWED_VIEWS_WITH_WEAK_PASSWORD = {
    'XFormListApi': {
        'GET': ['manifest', 'media', 'list',  'retrieve'],
    },
    'XFormSubmissionApi': {
       'POST': ['create'],
    },
}


class HTTPResponseNotAllowedMiddleware(MiddlewareMixin):

    def process_response(self, request, response):
        if isinstance(response, HttpResponseNotAllowed):
            response.content = loader.render_to_string(
                "405.html", request=request)

        return response


class LocaleMiddlewareWithTweaks(LocaleMiddleware):
    """
    Overrides LocaleMiddleware from django with:
        Khmer `km` language code in Accept-Language is rewritten to km-kh
    """

    def process_request(self, request):
        accept = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
        try:
            codes = [code for code, r in parse_accept_lang_header(accept)]
            if 'km' in codes and 'km-kh' not in codes:
                request.META['HTTP_ACCEPT_LANGUAGE'] = accept.replace('km',
                                                                      'km-kh')
        except:
            # this might fail if i18n is disabled.
            pass

        super().process_request(request)


class SqlLogging(MiddlewareMixin):
    def process_response(self, request, response):
        from sys import stdout
        if stdout.isatty():
            for query in connection.queries:
                print("\033[1;31m[%s]\033[0m \033[1m%s\033[0m" % (
                    query['time'], " ".join(query['sql'].split())))

        return response


class RestrictedAccessMiddleware(MiddlewareMixin):

    def __init__(self, get_response):
        super().__init__(get_response)
        self._allowed_view = None

    def process_response(self, request, response):
        if not request.user.is_authenticated:
            return response

        if isinstance(request.user, ServiceAccountUser):
            return response

        try:
            profile = request.user.profile
        except get_user_model().profile.RelatedObjectDoesNotExist:
            # Consider user's password as weak
            if not self._allowed_view:
                return self._render_response(response)

        if profile.validated_password:
            return response

        if not self._allowed_view:
            return self._render_response(response)

        return response

    def process_view(self, request, view, view_args, view_kwargs):
        """
        Validate if view is among allowed one with unsafe password.
        If it is not, set `self._allowed_view` to False to alter the
        response in `process_response()`.

        We cannot validate user's password here because DRF authentication
        takes places after this method call. Thus, `request.user` is always
        anonymous if user is authenticated with something else than the session.
        """
        view_name = view.__name__

        # Reset boolean for each processed view
        self._allowed_view = True

        if request.method == 'HEAD':
            return

        try:
            allowed_actions = ALLOWED_VIEWS_WITH_WEAK_PASSWORD[view_name][
                request.method
            ]
        except KeyError:
            self._allowed_view = False
        else:
            if hasattr(view, 'actions'):
                view_action = view.actions[request.method.lower()]
                if view_action not in allowed_actions:
                    self._allowed_view = False

        return

    def _render_response(
        self, response
    ) -> Union[
        HttpResponseForbidden, JsonResponseForbidden, XMLResponseForbidden
    ]:
        """
        Render response in the requested format: HTML, JSON or XML.
        If content type is not detected, fallback on HTML.
        """
        template = get_template('restricted_access.html')
        format_ = None
        try:
            content_type, *_ = response.accepted_media_type.split(';')
        except AttributeError:
            pass
        else:
            *_, format_ = content_type.split('/')

        if format_ not in ['xml', 'json']:
            return HttpResponseForbidden(template.render())
        else:
            data = {
                'detail': t(
                    f'Your access is restricted. Please reclaim your access by '
                    f'changing your password at '
                    f'{settings.KOBOFORM_URL}/accounts/password/reset/.'
                )
            }
            if format_ == 'json':
                return JsonResponseForbidden(data)
            else:
                return XMLResponseForbidden(
                    data, renderer_context=response.renderer_context
                )


class UsernameInResponseHeaderMiddleware(MiddlewareMixin):
    """
    Record the authenticated user (if any) in the `X-KoBoNaUt` HTTP header
    """
    def process_response(self, request, response):
        try:
            user = request.user
        except AttributeError:
            return response
        if user.is_authenticated:
            response['X-KoBoNaUt'] = request.user.username
        return response
