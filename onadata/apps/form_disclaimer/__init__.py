from django.apps import AppConfig


class FormDisclaimerAppConfig(AppConfig):
    name = 'onadata.apps.form_disclaimer'
    verbose_name = 'Form disclaimer'

    def ready(self):
        super().ready()
