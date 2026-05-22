from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_operationalsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="operationalsettings",
            name="label_printer_name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="operationalsettings",
            name="label_printer_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
