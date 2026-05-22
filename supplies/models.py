from __future__ import annotations

from django.db import models


class SupplyCategory(models.TextChoices):
	INGREDIENT = "ingredient", "Ingredient"
	PACKAGING = "packaging", "Packaging"
	SHIPPING_SUPPLY = "shipping_supply", "Shipping supply"
	EQUIPMENT = "equipment", "Equipment"
	OTHER = "other", "Other"


class Supply(models.Model):
	name = models.CharField(max_length=200, unique=True)
	sku_code = models.CharField(max_length=60, blank=True, help_text="Internal supply SKU/code (optional).")
	category = models.CharField(max_length=30, choices=SupplyCategory.choices, default=SupplyCategory.OTHER)
	unit = models.CharField(max_length=30, default="each", help_text="e.g. each, lb, oz, case")

	inventory_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
	low_stock_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=0)

	is_active = models.BooleanField(default=True)
	notes = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]
		indexes = [
			models.Index(fields=["category", "is_active"]),
		]

	def __str__(self) -> str:
		return self.name

	@property
	def is_low_stock(self) -> bool:
		return self.is_active and self.inventory_quantity <= self.low_stock_threshold
