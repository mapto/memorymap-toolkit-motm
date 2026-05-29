from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0012_timespan_certainty"),
    ]

    operations = [
        migrations.AddField(
            model_name="extraction",
            name="language",
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
