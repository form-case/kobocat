# coding: utf-8
import json
import logging
import os
import re
from urllib.parse import quote as urlquote

import rest_framework.request
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.storage import default_storage, FileSystemStorage
from django.urls import reverse
from django.db.models import Q
from django.http import (
    HttpResponseForbidden,
    HttpResponseRedirect,
    HttpResponseNotFound,
    HttpResponseBadRequest,
    HttpResponse,
)
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils.translation import gettext as t
from django.views.decorators.http import require_POST
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.settings import api_settings

from onadata.apps.logger.models import XForm, Attachment
from onadata.apps.viewer.models.export import Export
from onadata.apps.viewer.tasks import create_async_export
from onadata.libs.authentication import digest_authentication
from onadata.libs.utils.image_tools import image_url
from onadata.libs.utils.logger_tools import response_with_mimetype_and_name
from onadata.libs.utils.user_auth import (
    HttpResponseNotAuthorized,
    has_permission,
    helper_auth_helper,
)
from onadata.libs.utils.viewer_tools import export_def_from_filename

media_file_logger = logging.getLogger('media_files')


@login_required
@require_POST
def create_export(request, username, id_string, export_type):
    owner = get_object_or_404(User, username__iexact=username)
    xform = get_object_or_404(XForm, id_string__exact=id_string, user=owner)
    if not has_permission(xform, owner, request):
        return HttpResponseForbidden(t('Not shared.'))

    query = request.POST.get("query")
    force_xlsx = request.POST.get('xls') != 'true'

    # export options
    group_delimiter = request.POST.get("options[group_delimiter]", '/')
    if group_delimiter not in ['.', '/']:
        return HttpResponseBadRequest(
            t("%s is not a valid delimiter" % group_delimiter))

    # default is True, so when dont_.. is yes
    # split_select_multiples becomes False
    split_select_multiples = request.POST.get(
        "options[dont_split_select_multiples]", "no") == "no"

    binary_select_multiples = getattr(settings, 'BINARY_SELECT_MULTIPLES',
                                      False)
    options = {
        'group_delimiter': group_delimiter,
        'split_select_multiples': split_select_multiples,
        'binary_select_multiples': binary_select_multiples,
    }

    try:
        create_async_export(xform, export_type, query, force_xlsx, options)
    except Export.ExportTypeError:
        return HttpResponseBadRequest(
            t("%s is not a valid export type" % export_type))
    else:
        return HttpResponseRedirect(reverse(
            export_list,
            kwargs={
                "username": username,
                "id_string": id_string,
                "export_type": export_type
            })
        )


def export_list(request, username, id_string, export_type):
    try:
        Export.EXPORT_TYPE_DICT[export_type]
    except KeyError:
        return HttpResponseBadRequest(t('Invalid export type'))

    owner = get_object_or_404(User, username__iexact=username)
    xform = get_object_or_404(XForm, id_string__exact=id_string, user=owner)
    if not has_permission(xform, owner, request):
        return HttpResponseForbidden(t('Not shared.'))

    data = {
        'username': owner.username,
        'xform': xform,
        'export_type': export_type,
        'export_type_name': Export.EXPORT_TYPE_DICT[export_type],
        'exports': Export.objects.filter(
            xform=xform, export_type=export_type).order_by('-created_on')
    }

    return render(request, 'export_list.html', data)


def export_progress(request, username, id_string, export_type):
    owner = get_object_or_404(User, username__iexact=username)
    xform = get_object_or_404(XForm, id_string__exact=id_string, user=owner)
    if not has_permission(xform, owner, request):
        return HttpResponseForbidden(t('Not shared.'))

    # find the export entry in the db
    export_ids = request.GET.getlist('export_ids')
    exports = Export.objects.filter(xform=xform, id__in=export_ids)
    statuses = []
    for export in exports:
        status = {
            'complete': False,
            'url': None,
            'filename': None,
            'export_id': export.id
        }

        if export.status == Export.SUCCESSFUL:
            status['url'] = reverse(export_download, kwargs={
                'username': owner.username,
                'id_string': xform.id_string,
                'export_type': export.export_type,
                'filename': export.filename
            })
            status['filename'] = export.filename

        # mark as complete if it either failed or succeeded but NOT pending
        if export.status == Export.SUCCESSFUL or export.status == Export.FAILED:
            status['complete'] = True
        statuses.append(status)

    return HttpResponse(
        json.dumps(statuses), content_type='application/json')


def export_download(request, username, id_string, export_type, filename):
    owner = get_object_or_404(User, username__iexact=username)
    xform = get_object_or_404(XForm, id_string__exact=id_string, user=owner)
    helper_auth_helper(request)
    if not has_permission(xform, owner, request):
        return HttpResponseForbidden(t('Not shared.'))

    # find the export entry in the db
    export = get_object_or_404(Export, xform=xform, filename=filename)

    ext, mime_type = export_def_from_filename(export.filename)

    if not isinstance(default_storage, FileSystemStorage):
        return HttpResponseRedirect(default_storage.url(export.filepath))

    basename = os.path.splitext(export.filename)[0]
    response = response_with_mimetype_and_name(
        mime_type,
        name=basename,
        extension=ext,
        file_path=export.filepath,
        show_date=False,
    )
    return response


@login_required
@require_POST
def delete_export(request, username, id_string, export_type):
    owner = get_object_or_404(User, username__iexact=username)
    xform = get_object_or_404(XForm, id_string__exact=id_string, user=owner)
    if not has_permission(xform, owner, request):
        return HttpResponseForbidden(t('Not shared.'))

    export_id = request.POST.get('export_id')

    # find the export entry in the db
    export = get_object_or_404(Export, id=export_id)

    export.delete()
    return HttpResponseRedirect(reverse(
        export_list,
        kwargs={
            "username": username,
            "id_string": id_string,
            "export_type": export_type
        }))


def attachment_url(request, size='medium'):
    media_file = request.GET.get('media_file')

    # this assumes duplicates are the same file.
    #
    # Django seems to already handle that. It appends datetime to the filename.
    # It means duplicated would be only for the same user who uploaded two files
    # with same name at the same second.
    if media_file:
        # Strip out garbage (cache buster?) added by Galleria.js
        media_file = media_file.split('?')[0]
        mtch = re.search(r'^([^/]+)/attachments/([^/]+)$', media_file)
        if mtch:
            # in cases where the media_file url created by instance.html's
            # _attachment_url function is in the wrong format, this will
            # match attachments with the correct owner and the same file name
            (username, filename) = mtch.groups()
            result = Attachment.objects.filter(
                    instance__xform__user__username=username,
                ).filter(
                    Q(media_file_basename=filename) | Q(
                        media_file_basename=None,
                        media_file__endswith='/' + filename
                    )
                )[0:1]
        else:
            # search for media_file with exact matching name
            result = Attachment.objects.filter(media_file=media_file)[0:1]

        try:
            attachment = result[0]
        except IndexError:
            media_file_logger.info('attachment not found')
            return HttpResponseNotFound(t('Attachment not found'))

        # Attachment has a deleted date, it should not be shown anymore
        if attachment.deleted_at:
            return HttpResponseNotFound(_('Attachment not found'))

        # Checks whether users are allowed to see the media file before giving them
        # the url
        xform = attachment.instance.xform

        if not request.user.is_authenticated:
            # This is not a DRF view, but we need to honor things like
            # `DigestAuthentication` (ODK Briefcase uses it!) and
            # `TokenAuthentication`. Let's try all the DRF authentication
            # classes before giving up
            drf_request = rest_framework.request.Request(request)
            for auth_class in api_settings.DEFAULT_AUTHENTICATION_CLASSES:
                try:
                    # `authenticate()` will:
                    #   * return `None` if no applicable authentication attempt
                    #     was found in the request
                    #   * raise `AuthenticationFailed` if an attempt _was_
                    #     found but it failed
                    #   * return a tuple if authentication succeded
                    auth_tuple = auth_class().authenticate(drf_request)
                except AuthenticationFailed:
                    return HttpResponseNotAuthorized()
                if auth_tuple is not None:
                    # Is it kosher to modify `request`? Let's do it anyway
                    # since that's what `has_permission()` requires...
                    request.user = auth_tuple[0]
                    # `DEFAULT_AUTHENTICATION_CLASSES` are ordered and the
                    # first match wins; don't look any further
                    break

        if (
            not request.user.is_superuser
            and not has_permission(xform, xform.user, request)
        ):
            # New versions of ODK Briefcase (1.16+) do not sent Digest
            # authentication headers anymore directly. So, if user does not
            # pass `has_permission` and user is anonymous, we need to notify them
            # that access is unauthorized (i.e.: send a HTTP 401) and give them
            # a chance to authenticate.
            if request.user.is_anonymous:
                if digest_response := digest_authentication(request):
                    return digest_response

            # Otherwise, return a HTTP 403 (access forbidden)
            return HttpResponseForbidden(t('Not shared.'))

        media_url = None

        if not attachment.mimetype.startswith('image'):
            media_url = attachment.media_file.url
        else:
            try:
                media_url = image_url(attachment, size)
            except:
                media_file_logger.error(
                    'could not get thumbnail for image', exc_info=True
                )

        if media_url:
            # We want nginx to serve the media (instead of redirecting the media itself)
            # PROS:
            # - It avoids revealing the real location of the media.
            # - Full control on permission
            # CONS:
            # - When using S3 Storage, traffic is multiplied by 2.
            #    S3 -> Nginx -> User
            response = HttpResponse()
            if not isinstance(default_storage, FileSystemStorage):
                # Double-encode the S3 URL to take advantage of NGINX's
                # otherwise troublesome automatic decoding
                protected_url = '/protected-s3/{}'.format(urlquote(media_url))
            else:
                protected_url = media_url.replace(settings.MEDIA_URL, "/protected/")

            # Let nginx determine the correct content type
            response["Content-Type"] = ""
            response["X-Accel-Redirect"] = protected_url
            return response

    return HttpResponseNotFound(t('Error: Attachment not found'))
