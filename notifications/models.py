from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class StaffAlertEventType(models.TextChoices):
    NEW_PAID_ORDER = "new_paid_order", "New paid order"
    NEW_FUNDRAISER_SIGNUP = "new_fundraiser_signup", "New fundraiser signup"
    NEW_TEAM_CREATED = "new_team_created", "New team created"
    LOW_PRODUCT_INVENTORY = "low_product_inventory", "Low product inventory"
    LOW_SUPPLY_INVENTORY = "low_supply_inventory", "Low supply inventory"
    FAILED_PAYMENT = "failed_payment", "Failed payment"
    SHIPPING_LABEL_CREATED = "shipping_label_created", "Shipping label created"
    ADDRESS_VALIDATION_FAILED = "address_validation_failed", "Address validation failed"
    LARGE_ORDER_RECEIVED = "large_order_received", "Large order received"
    CSV_IMPORT_COMPLETED = "csv_import_completed", "CSV import completed"
    CSV_IMPORT_FAILED = "csv_import_failed", "CSV import failed"


class StaffAlertPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_alert_preference")
    enabled = models.BooleanField(default=True)

    receive_email = models.BooleanField(default=True)
    receive_sms = models.BooleanField(default=False)
    receive_internal = models.BooleanField(default=True)

    sms_opt_in = models.BooleanField(default=False)

    enabled_events = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"Staff alerts for {self.user.get_username()}"

    def is_event_enabled(self, event_type: str) -> bool:
        if not self.enabled:
            return False
        enabled = self.enabled_events or []
        if not enabled:
            return True
        return event_type in enabled


class NotificationEvent(models.Model):
    event_type = models.CharField(max_length=64, choices=StaffAlertEventType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    severity = models.CharField(max_length=20, default="info")

    # Optional linking
    order = models.ForeignKey("orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_events")
    team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_events")
    sku = models.ForeignKey("products.SKU", on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_events")

    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}: {self.title}"


class NotificationDeliveryStatus(models.TextChoices):
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class NotificationDeliveryChannel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    INTERNAL = "internal", "Internal"


class NotificationType(models.TextChoices):
    # Customer-facing
    NEW_ORDER = "new_order", "New order"
    ORDER_SHIPPED = "order_shipped", "Order shipped"
    DELIVERY_UPDATE = "delivery_update", "Delivery update"
    ABANDONED_CART_REMINDER = "abandoned_cart_reminder", "Abandoned cart reminder"

    # Fundraiser / team / seller
    FUNDRAISER_INVITE = "fundraiser_invite", "Fundraiser invite"
    TEAM_INVITE = "team_invite", "Team invite"
    SELLER_JOINED_TEAM = "seller_joined_team", "Seller joined team"
    TEAM_MILESTONE = "team_milestone", "Team milestone"

    # Operational (typically staff)
    LOW_INVENTORY = "low_inventory", "Low inventory"
    LOW_SUPPLIES = "low_supplies", "Low supplies"
    CSV_IMPORT_COMPLETE = "csv_import_complete", "CSV import complete"
    PAYMENT_FAILED = "payment_failed", "Payment failed"
    LABEL_CREATED = "label_created", "Label created"


class Notification(models.Model):
    """
    User-visible in-app notification.
    Keep payload safe; do not store sensitive payment details.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=64, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    order = models.ForeignKey("orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="user_notifications")

    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "read_at", "created_at"]),
            models.Index(fields=["user", "notification_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.notification_type} for {self.user.get_username()}"

    def mark_read(self):
        if self.read_at:
            return
        self.read_at = timezone.now()
        self.save(update_fields=["read_at"])


class NotificationPreference(models.Model):
    """
    Per-user notification settings for the unified notification center.

    SMS must also be consented to (UserProfile.sms_opt_in) and requires a phone number.
    If enabled_types is empty, all types are enabled by default.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_center_preference")
    enabled = models.BooleanField(default=True)

    receive_in_app = models.BooleanField(default=True)
    receive_email = models.BooleanField(default=True)
    receive_sms = models.BooleanField(default=False)

    sms_opt_in = models.BooleanField(default=False)
    enabled_types = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"Notification center prefs for {self.user.get_username()}"

    def is_type_enabled(self, notification_type: str) -> bool:
        if not self.enabled:
            return False
        enabled_types = self.enabled_types or []
        if not enabled_types:
            return True
        return notification_type in enabled_types


class NotificationDeliveryLog(models.Model):
    event = models.ForeignKey(NotificationEvent, on_delete=models.CASCADE, related_name="deliveries", null=True, blank=True)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_deliveries")
    channel = models.CharField(max_length=12, choices=NotificationDeliveryChannel.choices)
    status = models.CharField(max_length=10, choices=NotificationDeliveryStatus.choices, default=NotificationDeliveryStatus.SENT)

    recipient = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)

    failure_reason = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "channel", "status"]),
            models.Index(fields=["user", "read_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel} → {self.user.get_username()} [{self.status}]"

    def mark_read(self):
        if self.read_at:
            return
        self.read_at = timezone.now()
        self.save(update_fields=["read_at"])


class NotificationChannel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class NotificationStatus(models.TextChoices):
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class OrderNotification(models.Model):
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices)
    recipient = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=NotificationStatus.choices, default=NotificationStatus.SENT)
    failure_reason = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.channel} → {self.recipient} [{self.status}]"
