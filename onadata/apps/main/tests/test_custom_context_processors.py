# coding: utf-8
from django.test import override_settings, TestCase
from onadata.apps.main.context_processors import site_name


class CustomContextProcessorsTest(TestCase):
    @override_settings(KOBOCAT_PUBLIC_HOSTNAME="kc.form-case.org")
    def test_site_name(self):
        context = site_name(None)
        self.assertEqual(context, {'SITE_NAME': 'kc.form-case.org'})
