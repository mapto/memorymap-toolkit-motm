from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0011_concept_icon_parent"),
    ]

    operations = [
        migrations.AddField(
            model_name="timespan",
            name="certainty",
            field=models.CharField(
                blank=True,
                choices=[
                    ("certain", "Certain"),
                    ("probable", "Probable"),
                    ("uncertain", "Uncertain"),
                    ("disputed", "Disputed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="timespan",
            unique_together=set(),
        ),
    ]
