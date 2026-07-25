from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mpay', '0002_orderitem_product'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='stock_deducted',
            field=models.BooleanField(default=False, help_text='Stock has been deducted for this order'),
        ),
    ]
