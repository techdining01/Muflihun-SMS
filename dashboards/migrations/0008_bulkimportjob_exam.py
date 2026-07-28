from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboards', '0007_pushsubscription'),
        ('exams', '0005_add_description_term_to_exam'),
    ]

    operations = [
        migrations.AddField(
            model_name='bulkimportjob',
            name='exam',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='import_jobs',
                to='exams.exam',
            ),
        ),
    ]
