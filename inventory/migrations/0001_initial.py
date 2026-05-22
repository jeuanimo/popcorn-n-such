import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("cart", "0002_cartattribution_seller_store"),
        ("orders", "0005_checkout_system"),
        ("products", "0004_product_external_image_url_csvimportbatch_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryReservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "sku",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reservations",
                        to="products.sku",
                    ),
                ),
                (
                    "cart",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_reservations",
                        to="cart.cart",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="inventory_reservations",
                        to="orders.order",
                    ),
                ),
                ("quantity", models.PositiveIntegerField()),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="inventoryreservation",
            index=models.Index(fields=["sku", "expires_at"], name="inventory_r_sku_exp_idx"),
        ),
    ]
