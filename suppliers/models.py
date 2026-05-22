from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class SupplierCategory(models.TextChoices):
    INGREDIENTS = "ingredients", "Ingredients"
    PACKAGING = "packaging", "Packaging"
    SHIPPING_SUPPLIES = "shipping_supplies", "Shipping supplies"
    EQUIPMENT = "equipment", "Equipment"
    MARKETING = "marketing", "Marketing"
    TECHNOLOGY = "technology", "Technology"
    PAYMENT_SERVICES = "payment_services", "Payment services"
    MAINTENANCE = "maintenance", "Maintenance"
    WHOLESALE_FOOD_DISTRIBUTOR = "wholesale_food_distributor", "Wholesale food distributor"


class SupplierStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    category = models.CharField(max_length=40, choices=SupplierCategory.choices)
    status = models.CharField(max_length=12, choices=SupplierStatus.choices, default=SupplierStatus.ACTIVE)

    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)

    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="US")

    products_supplies_provided = models.TextField(blank=True, help_text="High-level description of products/supplies provided.")
    payment_terms = models.CharField(max_length=120, blank=True, help_text="e.g. Net 30, prepaid, COD.")
    average_lead_time_days = models.PositiveIntegerField(default=0)

    vendor_tax_id = models.CharField(max_length=80, blank=True, help_text="Optional vendor/tax ID.")
    rating = models.PositiveSmallIntegerField(default=0, help_text="0-5 internal rating.")
    notes = models.TextField(blank=True)

    last_contact_date = models.DateField(null=True, blank=True)
    next_follow_up_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_suppliers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "status"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == SupplierStatus.ACTIVE


class SupplierNote(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="crm_notes")
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Note for {self.supplier} ({self.created_at:%Y-%m-%d})"


class SupplierTaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    DONE = "done", "Done"
    CANCELLED = "cancelled", "Cancelled"


class SupplierTask(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="crm_tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=SupplierTaskStatus.choices, default=SupplierTaskStatus.OPEN)
    due_date = models.DateField(null=True, blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_supplier_tasks",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplier_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "-created_at"]
        indexes = [
            models.Index(fields=["status", "due_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.supplier})"


class SupplierDocument(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="suppliers/documents/%Y/%m/%d/")
    document_type = models.CharField(max_length=80, blank=True, help_text="e.g. contract, W-9, spec sheet.")
    notes = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_supplier_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.supplier})"


class SupplierPerformanceNote(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="performance_notes")
    rating_delta = models.SmallIntegerField(default=0, help_text="Optional +/- rating adjustment context.")
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_performance_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Performance note for {self.supplier} ({self.created_at:%Y-%m-%d})"


# ---------------------------------------------------------------------
# Purchase order history (minimal model to support supplier CRM)
# ---------------------------------------------------------------------


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    CONFIRMED = "confirmed", "Confirmed"
    RECEIVED = "received", "Received"
    CANCELLED = "cancelled", "Cancelled"


class SupplierPurchaseOrder(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    po_number = models.CharField(max_length=60, unique=True)
    status = models.CharField(max_length=12, choices=PurchaseOrderStatus.choices, default=PurchaseOrderStatus.DRAFT)
    payment_terms = models.CharField(max_length=120, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    total_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=10, default="USD")
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplier_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["supplier", "status"]),
        ]

    def __str__(self) -> str:
        return f"PO {self.po_number} ({self.supplier})"

    def mark_received(self, *, actor=None):
        self.status = PurchaseOrderStatus.RECEIVED
        self.received_date = timezone.localdate()
        self.save(update_fields=["status", "received_date", "updated_at"])
