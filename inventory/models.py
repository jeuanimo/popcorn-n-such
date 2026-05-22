from django.db import models


class InventoryReservation(models.Model):
    """
    Holds stock against a cart while the customer is in the checkout flow.
    Converted to a permanent decrement when the order is confirmed.
    """

    sku = models.ForeignKey("products.SKU", on_delete=models.PROTECT, related_name="reservations")
    cart = models.ForeignKey(
        "cart.Cart",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inventory_reservations",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_reservations",
    )
    quantity = models.PositiveIntegerField()
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["sku", "expires_at"])]

    def __str__(self) -> str:
        target = f"cart#{self.cart_id}" if self.cart_id else f"order#{self.order_id}"
        return f"Reserve {self.quantity}x SKU#{self.sku_id} for {target}"
