from django.db import models


class FulfillmentStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    PACKING = "packing", "Packing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"


class FulfillmentRecord(models.Model):
    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="fulfillment")
    status = models.CharField(max_length=20, choices=FulfillmentStatus.choices, default=FulfillmentStatus.QUEUED)
    warehouse_code = models.CharField(max_length=40, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    carrier = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-queued_at"]

    def __str__(self) -> str:
        return f"Fulfillment for {self.order} [{self.status}]"
