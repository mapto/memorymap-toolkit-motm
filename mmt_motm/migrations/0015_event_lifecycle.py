from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0014_locationpoint_concept"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="lifecycle",
            field=models.CharField(
                blank=True,
                choices=[
                    ("alte_heimat", "Alte Heimat"),
                    ("auswanderung", "Auswanderung"),
                    ("neue_heimat", "Neue Heimat"),
                    ("reise_zurueck", "Reise zurück"),
                    ("altro", "Altro"),
                ],
                default="altro",
                max_length=20,
            ),
        ),
    ]
