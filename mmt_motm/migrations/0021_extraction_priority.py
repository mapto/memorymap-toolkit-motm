from django.db import migrations, models


# markierung values from the source belege sheets map to an editorial
# priority rank: gelb (yellow highlight) is most important, cyan is
# secondary, ohne (no highlight) is least important. Anything else (blank,
# unrecognized values) has no priority.
CLASSIFICATION_TO_PRIORITY = {
    "gelb": 1,
    "cyan": 2,
    "ohne": 3,
}


def populate_priority(apps, schema_editor):
    Extraction = apps.get_model("mmt_motm", "Extraction")
    for classification, priority in CLASSIFICATION_TO_PRIORITY.items():
        Extraction.objects.filter(classification__iexact=classification).update(
            priority=priority
        )


def restore_classification(apps, schema_editor):
    Extraction = apps.get_model("mmt_motm", "Extraction")
    priority_to_classification = {
        priority: classification
        for classification, priority in CLASSIFICATION_TO_PRIORITY.items()
    }
    for priority, classification in priority_to_classification.items():
        Extraction.objects.filter(priority=priority).update(
            classification=classification
        )


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0020_merge_duplicate_concepts"),
    ]

    operations = [
        migrations.AddField(
            model_name="extraction",
            name="priority",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "High"), (2, "Medium"), (3, "Low")],
                null=True,
            ),
        ),
        migrations.RunPython(populate_priority, restore_classification),
        migrations.RemoveField(
            model_name="extraction",
            name="classification",
        ),
    ]
