from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0017_auto_20260828_1027"),
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
                    ("unknown", "Unknown"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]