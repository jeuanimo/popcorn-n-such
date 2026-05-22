from __future__ import annotations

from django.conf import settings
from django.db import models
_ORDER_FK = "orders.Order"


class PackageTemplate(models.Model):
    name = models.CharField(max_length=100)
    weight_oz = models.DecimalField(max_digits=8, decimal_places=2)
    length_in = models.DecimalField(max_digits=6, decimal_places=2)
    width_in = models.DecimalField(max_digits=6, decimal_places=2)
    height_in = models.DecimalField(max_digits=6, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.weight_oz} oz)"


class AddressValidation(models.Model):
    order = models.ForeignKey(
        _ORDER_FK,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="address_validations",
    )
    provider = models.CharField(max_length=50)

    # Raw input
    raw_recipient_name = models.CharField(max_length=200, blank=True)
    raw_address_line_1 = models.CharField(max_length=200)
    raw_address_line_2 = models.CharField(max_length=200, blank=True)
    raw_city = models.CharField(max_length=100)
    raw_state = models.CharField(max_length=50)
    raw_postal_code = models.CharField(max_length=20)
    raw_country = models.CharField(max_length=2, default="US")

    # Validated output
    validated_address_line_1 = models.CharField(max_length=200, blank=True)
    validated_address_line_2 = models.CharField(max_length=200, blank=True)
    validated_city = models.CharField(max_length=100, blank=True)
    validated_state = models.CharField(max_length=50, blank=True)
    validated_postal_code = models.CharField(max_length=20, blank=True)
    validated_country = models.CharField(max_length=2, blank=True)

    is_valid = models.BooleanField(default=False)
    is_corrected = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=500, blank=True)
    raw_response = models.JSONField(default=dict)

    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="address_validations",
    )
    validated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-validated_at"]

    def __str__(self) -> str:
        status = "valid" if self.is_valid else "invalid"
        return f"{self.raw_address_line_1}, {self.raw_city} [{status}]"


class ShippingRate(models.Model):
    order = models.ForeignKey(
        _ORDER_FK,
        on_delete=models.CASCADE,
        related_name="shipping_rates",
    )
    provider = models.CharField(max_length=50)
    carrier = models.CharField(max_length=100)
    service_name = models.CharField(max_length=200)
    service_code = models.CharField(max_length=100)
    rate_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    estimated_delivery_days = models.PositiveSmallIntegerField(null=True, blank=True)
    provider_rate_id = models.CharField(max_length=255)
    raw_response = models.JSONField(default=dict)
    is_selected = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rate_cents"]

    def __str__(self) -> str:
        return f"{self.carrier} {self.service_name} — ${self.rate_cents / 100:.2f}"


class ShippingLabel(models.Model):
    LABEL_FORMAT_CHOICES = [
        ("pdf_4x6", "PDF 4×6"),
        ("zpl", "ZPL Thermal"),
    ]

    order = models.ForeignKey(
        _ORDER_FK,
        on_delete=models.PROTECT,
        related_name="shipping_labels",
    )
    rate = models.ForeignKey(
        ShippingRate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labels",
    )
    provider = models.CharField(max_length=50)
    carrier = models.CharField(max_length=100)
    service_name = models.CharField(max_length=200)
    service_code = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=200, db_index=True)
    tracking_url = models.URLField(max_length=500, blank=True)

    label_format = models.CharField(max_length=20, choices=LABEL_FORMAT_CHOICES, default="pdf_4x6")
    # Stored internally; never exposed publicly without authorization
    label_url = models.CharField(max_length=500, blank=True)
    label_file = models.FileField(upload_to="shipping/labels/%Y/%m/%d/", blank=True)
    label_zpl = models.TextField(blank=True)  # raw ZPL for direct-to-thermal printing via QZ Tray

    rate_cents = models.PositiveIntegerField()
    provider_label_id = models.CharField(max_length=255)
    raw_response = models.JSONField(default=dict)

    package_weight_oz = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    package_length_in = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    package_width_in = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    package_height_in = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    is_voided = models.BooleanField(default=False, db_index=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_labels",
    )

    print_count = models.PositiveSmallIntegerField(default=0)
    first_printed_at = models.DateTimeField(null=True, blank=True)
    reprint_count = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_labels",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        voided = " [VOIDED]" if self.is_voided else ""
        return f"{self.tracking_number} — {self.carrier} {self.service_name}{voided}"

    @property
    def is_active(self) -> bool:
        return not self.is_voided


class ShipmentEvent(models.Model):
    """One carrier scan/event persisted from polling or webhook push."""

    label = models.ForeignKey(ShippingLabel, on_delete=models.CASCADE, related_name="events")
    event_code = models.CharField(max_length=50, blank=True)
    event_description = models.CharField(max_length=500)
    event_timestamp = models.DateTimeField(db_index=True)
    location = models.CharField(max_length=300, blank=True)
    raw = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_timestamp"]
        unique_together = [("label", "event_code", "event_timestamp")]

    def __str__(self) -> str:
        return f"{self.label.tracking_number} — {self.event_description} @ {self.event_timestamp}"
