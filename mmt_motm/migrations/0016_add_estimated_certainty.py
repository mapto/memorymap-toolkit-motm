from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0015_event_lifecycle"),
    ]

    operations = [
        migrations.AlterField(
            model_name="timespan",
            name="certainty",
            field=models.CharField(
                blank=True,
                choices=[
                    ("certain", "Certain"),
                    ("estimated", "Estimated"),
                    ("probable", "Probable"),
                    ("uncertain", "Uncertain"),
                    ("disputed", "Disputed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
