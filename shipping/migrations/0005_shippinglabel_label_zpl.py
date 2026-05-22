from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0004_shippinglabel_print_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinglabel",
            name="label_zpl",
            field=models.TextField(blank=True),
        ),
    ]
