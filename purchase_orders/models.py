from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class PurchaseOrderStatus(models.TextChoices):
	DRAFT = "draft", "Draft"
	SUBMITTED = "submitted", "Submitted"
	ORDERED = "ordered", "Ordered"
	PARTIALLY_RECEIVED = "partially_received", "Partially Received"
	RECEIVED = "received", "Received"
	CANCELED = "canceled", "Canceled"
	PAID = "paid", "Paid"


class PurchaseOrder(models.Model):
	po_number = models.CharField(max_length=60, unique=True, db_index=True)
	supplier = models.ForeignKey("suppliers.Supplier", on_delete=models.PROTECT, related_name="purchase_orders_v2")
	status = models.CharField(max_length=24, choices=PurchaseOrderStatus.choices, default=PurchaseOrderStatus.DRAFT)

	order_date = models.DateField(default=timezone.localdate)
	expected_delivery_date = models.DateField(null=True, blank=True)
	received_date = models.DateField(null=True, blank=True)

	subtotal_cents = models.PositiveIntegerField(default=0)
	tax_cents = models.PositiveIntegerField(default=0)
	shipping_cents = models.PositiveIntegerField(default=0)
	total_cents = models.PositiveIntegerField(default=0)
	currency = models.CharField(max_length=10, default="USD")

	notes = models.TextField(blank=True)
	invoice_file = models.FileField(upload_to="purchase_orders/invoices/%Y/%m/%d/", blank=True)

	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="created_purchase_orders",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-created_at"]
		indexes = [
			models.Index(fields=["supplier", "status"]),
		]

	def __str__(self) -> str:
		return f"PO {self.po_number} ({self.supplier.name})"

	def recalc_totals(self) -> None:
		subtotal = sum(int(item.line_total_cents) for item in self.items.all())
		self.subtotal_cents = max(0, subtotal)
		self.total_cents = max(0, self.subtotal_cents + self.tax_cents + self.shipping_cents)

	def clean(self):
		if self.total_cents and self.total_cents < (self.subtotal_cents + self.tax_cents + self.shipping_cents):
			raise ValidationError("Total cannot be less than subtotal + tax + shipping.")


class PurchaseOrderItem(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
	supply = models.ForeignKey("supplies.Supply", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
	sku = models.ForeignKey("products.SKU", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_items")
	description = models.CharField(max_length=255, blank=True)

	quantity_ordered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	quantity_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	unit_cost_cents = models.PositiveIntegerField(default=0)
	line_total_cents = models.PositiveIntegerField(default=0)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["id"]
		indexes = [
			models.Index(fields=["purchase_order"]),
		]

	def __str__(self) -> str:
		return f"Item #{self.pk} for {self.purchase_order.po_number}"

	def clean(self):
		if not self.supply_id and not self.sku_id and not self.description:
			raise ValidationError("Provide a supply, SKU, or description.")

	def recalc_line_total(self):
		qty = Decimal(self.quantity_ordered)
		self.line_total_cents = max(0, int(qty * Decimal(self.unit_cost_cents)))


class ReceivingEvent(models.Model):
	purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="receiving_events")
	item = models.ForeignKey(PurchaseOrderItem, on_delete=models.CASCADE, related_name="receiving_events")
	received_delta = models.DecimalField(max_digits=12, decimal_places=2)
	override_used = models.BooleanField(default=False)
	notes = models.CharField(max_length=255, blank=True)

	received_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="purchase_order_receiving_events",
	)
	received_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-received_at"]
		indexes = [
			models.Index(fields=["purchase_order", "received_at"]),
		]

	def __str__(self) -> str:
		return f"Receive {self.received_delta} for {self.purchase_order.po_number}"
