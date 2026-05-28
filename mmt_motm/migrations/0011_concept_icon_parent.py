from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mmt_motm', '0010_event_concepts_m2m'),
    ]

    operations = [
        migrations.AddField(
            model_name='concept',
            name='icon',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='concept',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='children',
                to='mmt_motm.concept',
            ),
        ),
    ]
