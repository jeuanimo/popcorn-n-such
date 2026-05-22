from __future__ import annotations

from django.conf import settings
from django.db import models


class PaymentProvider(models.TextChoices):
    GODADDY = "godaddy", "GoDaddy Payments"
    STRIPE = "stripe", "Stripe"
    PAYPAL = "paypal", "PayPal"


class PaymentStatus(models.TextChoices):
    CREATED = "created", "Created"
    PENDING = "pending", "Pending"
    AUTHORIZED = "authorized", "Authorized"
    CAPTURED = "captured", "Captured"
    CONFIRMED = "confirmed", "Confirmed"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    CANCELLED = "cancelled", "Cancelled"


class PaymentTransaction(models.Model):
    provider = models.CharField(max_length=32, choices=PaymentProvider.choices)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.CREATED)

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payment_transactions")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_transactions",
    )

    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=10, default="USD")

    # Safe references only: no PAN/CVV, only provider identifiers/links.
    provider_transaction_id = models.CharField(max_length=128, blank=True, db_index=True)
    provider_session_id = models.CharField(max_length=128, blank=True, db_index=True)
    checkout_url = models.URLField(blank=True)

    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    provider_metadata = models.JSONField(default=dict, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.status} {self.amount_cents}¢ → order #{self.order_id}"

    @property
    def is_confirmed(self) -> bool:
        return self.status == PaymentStatus.CONFIRMED


class PaymentEventLog(models.Model):
    provider = models.CharField(max_length=32, choices=PaymentProvider.choices)
    event_type = models.CharField(max_length=100)
    external_event_id = models.CharField(max_length=128, blank=True, db_index=True)

    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_logs",
    )

    signature_valid = models.BooleanField(default=False)
    request_id = models.CharField(max_length=128, blank=True)

    headers = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["provider", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_type} ({self.received_at:%Y-%m-%d %H:%M:%S})"
