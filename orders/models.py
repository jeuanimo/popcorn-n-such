from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending Payment"
    PAID = "paid", "Paid"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    CANCELED = "canceled", "Canceled"
    REFUNDED = "refunded", "Refunded"


# Backwards-compatible aliases (older code uses these names).
OrderStatus.DRAFT = OrderStatus.PENDING_PAYMENT
OrderStatus.PLACED = OrderStatus.PAID
OrderStatus.FULFILLING = OrderStatus.PROCESSING
OrderStatus.CANCELLED = OrderStatus.CANCELED


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    AUTHORIZED = "authorized", "Authorized"
    CAPTURED = "captured", "Captured"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class Order(models.Model):
    order_number = models.CharField(max_length=40, unique=True, null=True, blank=True, db_index=True)

    # Null for guest checkout — every order must have either customer or guest_email
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=25, blank=True)

    # Shipping address — snapshot taken at checkout, never mutated after
    shipping_recipient_name = models.CharField(max_length=150, blank=True)
    shipping_phone = models.CharField(max_length=25, blank=True)
    shipping_address_line_1 = models.CharField(max_length=255, blank=True)
    shipping_address_line_2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_state = models.CharField(max_length=100, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    shipping_country = models.CharField(max_length=2, default="US")

    # Billing address — snapshot taken at checkout
    billing_same_as_shipping = models.BooleanField(default=True)
    billing_recipient_name = models.CharField(max_length=150, blank=True)
    billing_address_line_1 = models.CharField(max_length=255, blank=True)
    billing_address_line_2 = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=2, default="US")

    # All pricing stored in cents — server-calculated, never browser-submitted
    subtotal_cents = models.PositiveIntegerField(default=0)
    tax_cents = models.PositiveIntegerField(default=0)
    shipping_cents = models.PositiveIntegerField(default=0)
    discount_cents = models.PositiveIntegerField(default=0)
    total_cents = models.PositiveIntegerField(default=0)
    coupon_code = models.CharField(max_length=40, blank=True)

    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING_PAYMENT, db_index=True
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )

    # Fundraiser attribution
    fundraiser_campaign = models.ForeignKey(
        "fundraisers.FundraiserCampaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    team = models.ForeignKey("teams.Team", on_delete=models.PROTECT, null=True, blank=True, related_name="orders")
    seller = models.ForeignKey(
        "sellers.SellerStore",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    fundraiser_code = models.CharField(max_length=50, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.order_number or f"Order #{self.pk}"

    @property
    def contact_email(self) -> str:
        if self.customer_id:
            return self.customer.email
        return self.guest_email

    def clean(self):
        if not self.customer_id and not self.guest_email:
            raise ValidationError("An order must have either an authenticated customer or a guest email.")

        if self.fundraiser_campaign and not self.fundraiser_campaign.is_accepting_orders():
            raise ValidationError("Only active campaigns in-date can accept fundraiser-attributed orders.")

        if self.team and not self.fundraiser_campaign:
            raise ValidationError("A campaign is required when attributing an order to a team.")

        if self.seller and not self.fundraiser_campaign:
            raise ValidationError("A campaign is required when attributing an order to a seller.")

        if self.fundraiser_campaign and self.team:
            if not self.fundraiser_campaign.teams.filter(id=self.team_id).exists():
                raise ValidationError("Selected team is not attached to this campaign.")

    def save(self, *args, **kwargs):
        if self.fundraiser_campaign_id:
            self.fundraiser_code = self.fundraiser_campaign.slug
        super().save(*args, **kwargs)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # Nullable so migrations work cleanly on empty tables; the checkout service always sets this.
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_items",
    )
    sku = models.ForeignKey("products.SKU", on_delete=models.PROTECT, related_name="order_items")
    product_name_snapshot = models.CharField(max_length=180)
    sku_snapshot = models.JSONField(default=dict)  # {sku_code, size, retail_price} at time of order
    quantity = models.PositiveIntegerField(default=1)
    unit_price_cents = models.PositiveIntegerField(default=0)
    line_total_cents = models.PositiveIntegerField(default=0)
    weight_ounces = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    fundraiser_eligible = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.product_name_snapshot} in {self.order}"


class SubscriptionInterval(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    BIWEEKLY = "biweekly", "Every 2 Weeks"
    MONTHLY = "monthly", "Monthly"
    EVERY_TWO_MONTHS = "every_2_months", "Every 2 Months"


_INTERVAL_DAYS: dict[str, int] = {
    SubscriptionInterval.WEEKLY: 7,
    SubscriptionInterval.BIWEEKLY: 14,
    SubscriptionInterval.MONTHLY: 30,
    SubscriptionInterval.EVERY_TWO_MONTHS: 60,
}


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    CANCELLED = "cancelled", "Cancelled"


class OrderSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="order_subscriptions",
    )
    source_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    interval = models.CharField(max_length=20, choices=SubscriptionInterval.choices)
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
        db_index=True,
    )
    next_order_date = models.DateField()
    last_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_renewals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Subscription {self.pk} ({self.get_interval_display()}) — {self.get_status_display()}"

    def advance_next_date(self) -> None:
        import datetime
        self.next_order_date = datetime.date.today() + datetime.timedelta(
            days=_INTERVAL_DAYS[self.interval]
        )


class OrderSubscriptionItem(models.Model):
    subscription = models.ForeignKey(
        OrderSubscription, on_delete=models.CASCADE, related_name="items"
    )
    sku = models.ForeignKey(
        "products.SKU", on_delete=models.CASCADE, related_name="subscription_items"
    )
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = [("subscription", "sku")]

    def __str__(self) -> str:
        return f"{self.quantity}x SKU {self.sku_id} in subscription {self.subscription_id}"
