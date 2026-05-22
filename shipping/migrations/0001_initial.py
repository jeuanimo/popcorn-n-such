from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("orders", "0005_checkout_system"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PackageTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("weight_oz", models.DecimalField(decimal_places=2, max_digits=8)),
                ("length_in", models.DecimalField(decimal_places=2, max_digits=6)),
                ("width_in", models.DecimalField(decimal_places=2, max_digits=6)),
                ("height_in", models.DecimalField(decimal_places=2, max_digits=6)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="AddressValidation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="address_validations",
                        to="orders.order",
                    ),
                ),
                ("provider", models.CharField(max_length=50)),
                ("raw_recipient_name", models.CharField(blank=True, max_length=200)),
                ("raw_address_line_1", models.CharField(max_length=200)),
                ("raw_address_line_2", models.CharField(blank=True, max_length=200)),
                ("raw_city", models.CharField(max_length=100)),
                ("raw_state", models.CharField(max_length=50)),
                ("raw_postal_code", models.CharField(max_length=20)),
                ("raw_country", models.CharField(default="US", max_length=2)),
                ("validated_address_line_1", models.CharField(blank=True, max_length=200)),
                ("validated_address_line_2", models.CharField(blank=True, max_length=200)),
                ("validated_city", models.CharField(blank=True, max_length=100)),
                ("validated_state", models.CharField(blank=True, max_length=50)),
                ("validated_postal_code", models.CharField(blank=True, max_length=20)),
                ("validated_country", models.CharField(blank=True, max_length=2)),
                ("is_valid", models.BooleanField(default=False)),
                ("is_corrected", models.BooleanField(default=False)),
                ("failure_reason", models.CharField(blank=True, max_length=500)),
                ("raw_response", models.JSONField(default=dict)),
                (
                    "validated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="address_validations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("validated_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-validated_at"],
            },
        ),
        migrations.CreateModel(
            name="ShippingRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shipping_rates",
                        to="orders.order",
                    ),
                ),
                ("provider", models.CharField(max_length=50)),
                ("carrier", models.CharField(max_length=100)),
                ("service_name", models.CharField(max_length=200)),
                ("service_code", models.CharField(max_length=100)),
                ("rate_cents", models.PositiveIntegerField()),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("estimated_delivery_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("provider_rate_id", models.CharField(max_length=255)),
                ("raw_response", models.JSONField(default=dict)),
                ("is_selected", models.BooleanField(default=False)),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["rate_cents"],
            },
        ),
        migrations.CreateModel(
            name="ShippingLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shipping_labels",
                        to="orders.order",
                    ),
                ),
                (
                    "rate",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="labels",
                        to="shipping.shippingrate",
                    ),
                ),
                ("provider", models.CharField(max_length=50)),
                ("carrier", models.CharField(max_length=100)),
                ("service_name", models.CharField(max_length=200)),
                ("tracking_number", models.CharField(db_index=True, max_length=200)),
                ("tracking_url", models.URLField(blank=True, max_length=500)),
                (
                    "label_format",
                    models.CharField(
                        choices=[("pdf_4x6", "PDF 4×6"), ("zpl", "ZPL Thermal")],
                        default="pdf_4x6",
                        max_length=20,
                    ),
                ),
                ("label_url", models.CharField(blank=True, max_length=500)),
                ("rate_cents", models.PositiveIntegerField()),
                ("provider_label_id", models.CharField(max_length=255)),
                ("raw_response", models.JSONField(default=dict)),
                ("is_voided", models.BooleanField(db_index=True, default=False)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "voided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="voided_labels",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("reprint_count", models.PositiveSmallIntegerField(default=0)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_labels",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
