from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0013_add_extraction_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationpoint",
            name="concept",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="location_point",
                to="mmt_motm.concept",
            ),
        ),
    ]
