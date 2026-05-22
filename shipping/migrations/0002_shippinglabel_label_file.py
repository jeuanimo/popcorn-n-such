from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="shippinglabel",
            name="label_file",
            field=models.FileField(blank=True, upload_to="shipping/labels/%Y/%m/%d/"),
        ),
    ]

