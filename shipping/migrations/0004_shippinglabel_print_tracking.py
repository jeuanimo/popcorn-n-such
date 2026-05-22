from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0003_shippinglabel_package_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinglabel",
            name="print_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="shippinglabel",
            name="first_printed_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
