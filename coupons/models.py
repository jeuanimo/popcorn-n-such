from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.validators import validate_json_dict


class CouponDiscountType(models.TextChoices):
    PERCENT = "percent", "Percent"
    FIXED = "fixed", "Fixed amount"


class Coupon(models.Model):
    code = models.CharField(max_length=40, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)

    discount_type = models.CharField(max_length=10, choices=CouponDiscountType.choices)
    # Percent: 0-100 (supports two decimals)
    percent_off = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    # Fixed: stored in cents
    amount_off_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Total maximum uses across all customers.")
    per_customer_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum uses per customer.")

    applies_to_products = models.ManyToManyField("products.Product", blank=True, related_name="coupons")
    applies_to_categories = models.ManyToManyField("products.ProductCategory", blank=True, related_name="coupons")

    applies_to_fundraiser_orders = models.BooleanField(
        default=True,
        help_text="If false, fundraiser-attributed orders cannot use this coupon.",
    )
    minimum_cart_subtotal_cents = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "code"]

    def __str__(self) -> str:
        return self.code

    def clean(self):
        self.code = (self.code or "").strip().upper()
        if not self.code:
            raise ValidationError("Coupon code is required.")
        if self.discount_type == CouponDiscountType.PERCENT and self.percent_off <= 0:
            raise ValidationError("Percent-off coupons must have a positive percent_off.")
        if self.discount_type == CouponDiscountType.FIXED and self.amount_off_cents <= 0:
            raise ValidationError("Fixed-amount coupons must have a positive amount_off_cents.")
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("Coupon end date must be on or after start date.")

    def is_within_date_range(self, *, as_of=None) -> bool:
        today = as_of or timezone.localdate()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        return True


class CouponRedemption(models.Model):
    """
    Coupon usage record. Created only after a paid order is confirmed.
    """

    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="coupon_redemption")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coupon_redemptions",
    )
    redeemed_at = models.DateTimeField(auto_now_add=True)
    discount_cents = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True, validators=[validate_json_dict])

    class Meta:
        ordering = ["-redeemed_at"]
        indexes = [
            models.Index(fields=["coupon", "redeemed_at"]),
            models.Index(fields=["customer", "redeemed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.coupon.code} on {self.order}"

