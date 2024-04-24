from django.conf import settings
from django.core.files.storage import default_storage
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from guardian.shortcuts import assign_perm, get_perms_for_model

from onadata.apps.logger.models import XForm
from onadata.apps.viewer.models.data_dictionary import DataDictionary
from onadata.apps.viewer.models.export import Export
from onadata.apps.viewer.models.parsed_instance import ParsedInstance


@receiver(post_delete, sender=Export)
def export_delete_callback(sender, **kwargs):
    export = kwargs['instance']
    if export.filepath and default_storage.exists(export.filepath):
        default_storage.delete(export.filepath)


@receiver(post_save, sender=DataDictionary, dispatch_uid='xform_object_permissions')
def set_object_permissions(sender, instance=None, created=False, **kwargs):
    if created:
        for perm in get_perms_for_model(XForm):
            assign_perm(perm.codename, instance.user, instance)


@receiver(pre_delete, sender=ParsedInstance)
def remove_from_mongo(sender, **kwargs):
    instance_id = kwargs.get('instance').instance.id
    settings.MONGO_DB.instances.delete_one({'_id': instance_id})
