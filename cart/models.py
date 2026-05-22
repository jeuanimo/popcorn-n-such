from decimal import Decimal

from django.conf import settings
from django.db import models


class Cart(models.Model):
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		null=True,
		blank=True,
		related_name="carts",
	)
	session_key = models.CharField(max_length=64, blank=True, db_index=True)
	is_active = models.BooleanField(default=True)
	coupon_code = models.CharField(max_length=40, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-updated_at"]

	def __str__(self) -> str:
		identity = self.user.get_username() if self.user else self.session_key
		return f"Cart #{self.pk} ({identity})"

	@property
	def items_subtotal(self) -> Decimal:
		subtotal = Decimal("0.00")
		for item in self.items.select_related("sku").all():
			subtotal += item.subtotal
		return subtotal


class CartItem(models.Model):
	cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
	sku = models.ForeignKey("products.SKU", on_delete=models.PROTECT, related_name="cart_items")
	quantity = models.PositiveIntegerField(default=1)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = ("cart", "sku")
		ordering = ["-updated_at"]

	@property
	def unit_price(self) -> Decimal:
		# Server-authoritative price source.
		return self.sku.retail_price

	@property
	def subtotal(self) -> Decimal:
		return self.unit_price * self.quantity


class SavedForLaterItem(models.Model):
	cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="saved_items")
	sku = models.ForeignKey("products.SKU", on_delete=models.PROTECT, related_name="saved_for_later_items")
	quantity = models.PositiveIntegerField(default=1)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = ("cart", "sku")
		ordering = ["-updated_at"]


class CartAttribution(models.Model):
	cart = models.OneToOneField(Cart, on_delete=models.CASCADE, related_name="attribution")
	fundraiser_campaign = models.CharField(max_length=120, blank=True)
	team = models.CharField(max_length=120, blank=True)
	seller = models.CharField(max_length=120, blank=True)
	# Secure FK-based fundraiser attribution (preferred)
	campaign = models.ForeignKey(
		"fundraisers.FundraiserCampaign",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="cart_attributions",
	)
	team_ref = models.ForeignKey(
		"teams.Team",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="cart_attributions",
	)
	# Secure FK-based seller store attribution (not user-editable via URL params)
	seller_store = models.ForeignKey(
		"sellers.SellerStore",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="cart_attributions",
	)
	share_link = models.ForeignKey(
		"sharing.ShareLink",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="cart_attributions",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return f"Attribution for cart #{self.cart_id}"
