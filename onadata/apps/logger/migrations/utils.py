def delete_null_user_daily_counters(apps, schema_editor):

    DailyXFormSubmissionCounter = apps.get_model('logger', 'DailyXFormSubmissionCounter')  # noqa

    counters_without_users = DailyXFormSubmissionCounter.objects.filter(user=None)

    if not counters_without_users.exists():
        return

    # Associate each daily counter with user=None with a user based on its xform
    batch = []
    batch_size = 5000
    for counter in (
            counters_without_users
            .exclude(xform=None)
            .exclude(xform__user=None)
            .iterator()
    ):
        counter.user = counter.xform.user
        # don't add a user to duplicate counters, so they get deleted when we're done looping
        if DailyXFormSubmissionCounter.objects.filter(
                date=counter.date, xform=counter.xform
        ).exclude(user=None).exists():
            continue
        batch.append(counter)
        if len(batch) >= batch_size:
            DailyXFormSubmissionCounter.objects.bulk_update(batch, ['user_id'])
            batch = []
    if batch:
        DailyXFormSubmissionCounter.objects.bulk_update(batch, ['user_id'])

    # Delete daily counters without a user to avoid creating invalid monthly counters
    DailyXFormSubmissionCounter.objects.filter(user=None).delete()
