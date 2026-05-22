import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("orders", "0005_checkout_system"),
    ]

    operations = [
        migrations.CreateModel(
            name="FulfillmentRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fulfillment",
                        to="orders.order",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("packing", "Packing"),
                            ("packed", "Packed"),
                            ("shipped", "Shipped"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("warehouse_code", models.CharField(blank=True, max_length=40)),
                ("tracking_number", models.CharField(blank=True, max_length=100)),
                ("carrier", models.CharField(blank=True, max_length=60)),
                ("notes", models.TextField(blank=True)),
                ("queued_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-queued_at"],
            },
        ),
    ]
