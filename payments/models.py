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
    # Set when a charge request was sent but the outcome is unknown (timeout /
    # dropped connection). MUST NOT be retried blindly — see reconciliation.
    AMBIGUOUS = "ambiguous", "Ambiguous (needs reconciliation)"


class PaymentTransaction(models.Model):
    provider = models.CharField(max_length=32, choices=PaymentProvider.choices)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.CREATED)

    # Nullable: an attempt row is written before the provider is called, and the
    # order is only created once the provider confirms. Failed and ambiguous
    # attempts therefore persist without an order attached.
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_transactions",
    )
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

    # PCI-safe card descriptors only. Never PAN, CVV, or expiration date.
    card_brand = models.CharField(max_length=32, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)
    avs_result = models.CharField(max_length=32, blank=True)
    cvv_result = models.CharField(max_length=32, blank=True)

    # Ambiguous-outcome recovery (network failure after the charge was sent).
    requires_reconciliation = models.BooleanField(default=False, db_index=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciliation_attempts = models.PositiveSmallIntegerField(default=0)

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
        constraints = [
            # A given idempotency key may only ever map to one charge attempt,
            # so a replayed POST cannot open a second attempt against the provider.
            models.UniqueConstraint(
                fields=["provider", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_payment_provider_idempotency_key",
            ),
            # Database-level backstop against double-charging an order: at most
            # one confirmed transaction may exist per order.
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status__in=["confirmed", "captured"], order__isnull=False),
                name="uniq_confirmed_payment_per_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.status} {self.amount_cents}¢ → order #{self.order_id}"

    #: Statuses that mean the customer's money has been taken.
    PAID_STATUSES = frozenset({PaymentStatus.CONFIRMED, PaymentStatus.CAPTURED})

    @property
    def is_confirmed(self) -> bool:
        return self.status in self.PAID_STATUSES

    @property
    def is_settled(self) -> bool:
        """Terminal state — no further provider interaction is expected."""
        return self.status in {
            PaymentStatus.CONFIRMED,
            PaymentStatus.CAPTURED,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
            PaymentStatus.CANCELLED,
        }

    @property
    def card_display(self) -> str:
        if not self.card_last4:
            return ""
        return f"{self.card_brand or 'Card'} ••••{self.card_last4}".strip()


class PaymentRefund(models.Model):
    """
    A refund issued against a PaymentTransaction.

    Refunds are recorded as their own rows rather than by mutating or deleting
    the original payment: the original charge remains the permanent record of
    money taken, and each refund references it.
    """

    payment = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.PROTECT,
        related_name="refunds",
    )
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    provider_refund_id = models.CharField(max_length=128, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    provider_metadata = models.JSONField(default=dict, blank=True)

    reason = models.CharField(max_length=255, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_refunds",
    )

    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="uniq_refund_idempotency_key",
            ),
        ]

    def __str__(self) -> str:
        return f"Refund {self.amount_cents}¢ of payment #{self.payment_id} ({self.status})"


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
