from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mmt_motm', '0009_alter_timespan_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='concepts',
            field=models.ManyToManyField(blank=True, related_name='events', to='mmt_motm.Concept'),
        ),
    ]
