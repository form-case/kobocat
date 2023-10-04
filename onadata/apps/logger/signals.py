# coding: utf-8
import logging

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.db.models.signals import (
    post_save,
    pre_delete,
)
from django.dispatch import receiver

from onadata.apps.logger.models.attachment import Attachment
from onadata.apps.logger.models.xform import XForm
from onadata.apps.main.models.user_profile import UserProfile


@receiver(pre_delete, sender=Attachment)
def pre_delete_attachment(instance, **kwargs):
    # "Model.delete() isn’t called on related models, but the pre_delete and
    # post_delete signals are sent for all deleted objects." See
    # https://docs.djangoproject.com/en/3.2/ref/models/fields/#django.db.models.CASCADE
    # We want to delete all files when an XForm, an Instance or Attachment object is
    # deleted.
    # Since the Attachment object is deleted with CASCADE, we must use a
    # `pre_delete` signal to access its parent Instance and its parent XForm.
    # Otherwise, with a `post_delete`, they would be gone before reaching the rest
    # of code below.

    # `instance` here means "model instance", and no, it is not allowed to
    # change the name of the parameter
    attachment = instance
    file_size = attachment.media_file_size

    xform = attachment.instance.xform

    if file_size:
        with transaction.atomic():
            """
            Update both counters at the same time (in a transaction) to avoid 
            desynchronization as much as possible 
            """
            UserProfile.objects.filter(
                user_id=xform.user_id
            ).update(
                attachment_storage_bytes=F('attachment_storage_bytes') - file_size
            )
            XForm.all_objects.filter(pk=xform.pk).update(
                attachment_storage_bytes=F('attachment_storage_bytes') - file_size
            )

    if not (media_file_name := str(attachment.media_file)):
        return

    # Clean-up storage
    try:
        # We do not want to call `attachment.media_file.delete()` because it calls
        # `attachment.save()` behind the scene which would call again the `post_save`
        # signal below. Bonus: it avoids an extra query 😎.
        default_storage.delete(media_file_name)
    except Exception as e:
        logging.error('Failed to delete attachment: ' + str(e), exc_info=True)


@receiver(post_save, sender=Attachment)
def post_save_attachment(instance, created, **kwargs):
    """
    Update the attachment_storage_bytes field in the UserProfile model
    when an attachment is added
    """
    if not created:
        return
    attachment = instance
    if getattr(attachment, 'defer_counting', False):
        return

    file_size = attachment.media_file_size
    if not file_size:
        return

    with transaction.atomic():
        xform = attachment.instance.xform

        UserProfile.objects.filter(user_id=xform.user_id).update(
            attachment_storage_bytes=F('attachment_storage_bytes') + file_size
        )
        XForm.objects.filter(pk=xform.pk).update(
            attachment_storage_bytes=F('attachment_storage_bytes') + file_size
        )
