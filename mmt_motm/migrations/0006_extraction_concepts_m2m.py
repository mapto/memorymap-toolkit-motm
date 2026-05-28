# Generated manually — converts Extraction.concepts from ForeignKey to ManyToManyField

from django.db import migrations, models


def copy_fk_to_m2m(apps, schema_editor):
    """Copy existing FK concept references into the new M2M relation."""
    Extraction = apps.get_model("mmt_motm", "Extraction")
    for extraction in Extraction.objects.filter(concepts_old__isnull=False):
        extraction.concepts.add(extraction.concepts_old)


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0005_concept_extraction"),
    ]

    operations = [
        # 1. Rename old FK field
        migrations.RenameField(
            model_name="extraction",
            old_name="concepts",
            new_name="concepts_old",
        ),
        # 2. Add new M2M field
        migrations.AddField(
            model_name="extraction",
            name="concepts",
            field=models.ManyToManyField(
                blank=True,
                related_name="relates_to_concept",
                to="mmt_motm.Concept",
            ),
        ),
        # 3. Copy data from FK to M2M
        migrations.RunPython(copy_fk_to_m2m, migrations.RunPython.noop),
        # 4. Remove old FK field
        migrations.RemoveField(
            model_name="extraction",
            name="concepts_old",
        ),
    ]
