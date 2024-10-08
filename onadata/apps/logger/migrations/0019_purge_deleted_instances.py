# Generated by Django 2.2.14 on 2021-06-30 19:00
from django.conf import settings
from django.db import migrations


def purge_deleted_instances(apps, schema_editor):
    """
    Remove all submissions that have been already marked as deleted from both
    PostgreSQL and MongoDB. If this is too slow, revert to a previous release
    and run the code in
    https://github.com/form-case/kobocat/issues/696#issuecomment-809622367
    using `manage.py shell_plus`.
    """
    Instance = apps.get_model('logger', 'Instance')
    to_purge = Instance.objects.exclude(deleted_at=None).only('pk')
    if not to_purge.exists():
        return
    print(
        f'Purging {to_purge.count()} deleted instances...', end='', flush=True
    )
    for instance in to_purge.iterator():
        # Manually delete from MongoDB because signals are not called in
        # migrations (that would require freezing all application code, not
        # just the models!)
        settings.MONGO_DB.instances.delete_one({'_id': instance.pk})
        instance.delete()
    print('Done!', flush=True)


def do_nothing(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('logger', '0018_add_submission_counter'),
    ]
    operations = [
        migrations.RunPython(
            purge_deleted_instances, reverse_code=do_nothing
        ),
    ]
