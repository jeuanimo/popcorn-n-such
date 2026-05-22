from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("products", "0001_initial"),
        ("orders", "0005_checkout_system"),
    ]

    operations = [
        migrations.CreateModel(
            name="Coupon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=40, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("discount_type", models.CharField(choices=[("percent", "Percent"), ("fixed", "Fixed amount")], max_length=10)),
                (
                    "percent_off",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=6,
                    ),
                ),
                ("amount_off_cents", models.PositiveIntegerField(default=0)),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("usage_limit", models.PositiveIntegerField(blank=True, help_text="Total maximum uses across all customers.", null=True)),
                ("per_customer_limit", models.PositiveIntegerField(blank=True, help_text="Maximum uses per customer.", null=True)),
                ("applies_to_fundraiser_orders", models.BooleanField(default=True, help_text="If false, fundraiser-attributed orders cannot use this coupon.")),
                ("minimum_cart_subtotal_cents", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "applies_to_categories",
                    models.ManyToManyField(blank=True, related_name="coupons", to="products.productcategory"),
                ),
                (
                    "applies_to_products",
                    models.ManyToManyField(blank=True, related_name="coupons", to="products.product"),
                ),
            ],
            options={"ordering": ["-created_at", "code"]},
        ),
        migrations.CreateModel(
            name="CouponRedemption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("redeemed_at", models.DateTimeField(auto_now_add=True)),
                ("discount_cents", models.PositiveIntegerField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "coupon",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redemptions", to="coupons.coupon"),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="coupon_redemptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="coupon_redemption", to="orders.order"),
                ),
            ],
            options={"ordering": ["-redeemed_at"]},
        ),
        migrations.AddIndex(
            model_name="couponredemption",
            index=models.Index(fields=["coupon", "redeemed_at"], name="coupons_co_coupon__ae5a5e_idx"),
        ),
        migrations.AddIndex(
            model_name="couponredemption",
            index=models.Index(fields=["customer", "redeemed_at"], name="coupons_co_customer_5a7cda_idx"),
        ),
    ]

