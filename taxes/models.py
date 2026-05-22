from __future__ import annotations

from django.conf import settings
from django.db import models


class TaxProviderSlug(models.TextChoices):
    MANUAL = "manual", "Manual"
    TAXJAR = "taxjar", "TaxJar"
    AVALARA = "avalara", "Avalara"


class TaxCalculation(models.Model):
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tax_calculations",
    )
    cart = models.ForeignKey(
        "cart.Cart",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tax_calculations",
    )

    provider = models.CharField(max_length=32, choices=TaxProviderSlug.choices)
    provider_reference_id = models.CharField(max_length=128, blank=True, db_index=True)

    shipping_address_line_1 = models.CharField(max_length=255, blank=True)
    shipping_address_line_2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_state = models.CharField(max_length=100, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    shipping_country = models.CharField(max_length=2, default="US")

    taxable_subtotal_cents = models.PositiveIntegerField(default=0)
    shipping_cents = models.PositiveIntegerField(default=0)
    tax_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=10, default="USD")

    jurisdiction_data = models.JSONField(default=dict, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)

    is_final = models.BooleanField(
        default=False,
        help_text="Final tax snapshot for a paid order; do not recalculate automatically.",
    )

    succeeded = models.BooleanField(default=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)

    calculated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tax_calculations",
    )
    calculated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["provider", "calculated_at"]),
        ]

    def __str__(self) -> str:
        target = f"order#{self.order_id}" if self.order_id else f"cart#{self.cart_id}"
        return f"{self.provider} tax {self.tax_cents}¢ ({target})"
