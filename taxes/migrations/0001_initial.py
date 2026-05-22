from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cart", "0002_cartattribution_seller_store"),
        ("orders", "0004_order_seller_store"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaxCalculation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "provider",
                    models.CharField(
                        choices=[("manual", "Manual"), ("taxjar", "TaxJar"), ("avalara", "Avalara")], max_length=32
                    ),
                ),
                ("provider_reference_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("shipping_address_line_1", models.CharField(blank=True, max_length=255)),
                ("shipping_address_line_2", models.CharField(blank=True, max_length=255)),
                ("shipping_city", models.CharField(blank=True, max_length=100)),
                ("shipping_state", models.CharField(blank=True, max_length=100)),
                ("shipping_postal_code", models.CharField(blank=True, max_length=20)),
                ("shipping_country", models.CharField(default="US", max_length=2)),
                ("taxable_subtotal_cents", models.PositiveIntegerField(default=0)),
                ("shipping_cents", models.PositiveIntegerField(default=0)),
                ("tax_cents", models.PositiveIntegerField(default=0)),
                ("currency", models.CharField(default="USD", max_length=10)),
                ("jurisdiction_data", models.JSONField(blank=True, default=dict)),
                ("provider_metadata", models.JSONField(blank=True, default=dict)),
                (
                    "is_final",
                    models.BooleanField(
                        default=False,
                        help_text="Final tax snapshot for a paid order; do not recalculate automatically.",
                    ),
                ),
                ("succeeded", models.BooleanField(default=True)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("failure_message", models.TextField(blank=True)),
                ("calculated_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "calculated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tax_calculations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "cart",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tax_calculations",
                        to="cart.cart",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tax_calculations",
                        to="orders.order",
                    ),
                ),
            ],
            options={
                "ordering": ["-calculated_at"],
                "indexes": [
                    models.Index(fields=["provider", "calculated_at"], name="taxes_taxc_provider_12fced_idx"),
                ],
            },
        ),
    ]

