from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0002_shippinglabel_label_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinglabel",
            name="service_code",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="shippinglabel",
            name="package_height_in",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="shippinglabel",
            name="package_length_in",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name="shippinglabel",
            name="package_weight_oz",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name="shippinglabel",
            name="package_width_in",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6),
        ),
    ]

