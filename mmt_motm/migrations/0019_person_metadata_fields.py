from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mmt_motm", "0018_add_unknown_certainty"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="education",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="person",
            name="occupation_at_emigration",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="person",
            name="occupation_at_source",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="person",
            name="residence_at_source",
            field=models.TextField(blank=True, default=""),
        ),
    ]