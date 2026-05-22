from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_checkout_system"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="coupon_code",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]

