from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class ProductCategory(models.Model):
	key = models.SlugField(max_length=40, unique=True)
	name = models.CharField(max_length=80, unique=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["name"]

	def __str__(self) -> str:
		return self.name


class ProductQuerySet(models.QuerySet):
	def active(self):
		return self.filter(is_active=True)

	def public_store(self):
		return self.active().filter(standalone_store_eligible=True)

	def fundraiser_store(self):
		return self.active().filter(fundraiser_eligible=True)


class Product(models.Model):
	name = models.CharField(max_length=180)
	slug = models.SlugField(max_length=220, unique=True)
	description = models.TextField(blank=True)
	category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="products")
	flavor = models.CharField(max_length=120)
	image = models.ImageField(upload_to="products/", blank=True, null=True)
	external_image_url = models.URLField(blank=True)
	is_active = models.BooleanField(default=True)
	is_featured = models.BooleanField(default=False)
	fundraiser_eligible = models.BooleanField(default=True)
	standalone_store_eligible = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	objects = ProductQuerySet.as_manager()

	class Meta:
		ordering = ["name"]

	def __str__(self) -> str:
		return self.name

	def save(self, *args, **kwargs):
		if not self.slug:
			self.slug = slugify(self.name)
		super().save(*args, **kwargs)

	@property
	def primary_cart_sku(self):
		return self.skus.purchasable().first()


class SKUQuerySet(models.QuerySet):
	def active(self):
		return self.filter(is_active=True, product__is_active=True)

	def purchasable(self):
		return self.active().filter(inventory_quantity__gt=0)

	def low_stock(self):
		return self.filter(inventory_quantity__lte=models.F("low_stock_threshold"))


class SKU(models.Model):
	sku_code = models.CharField(max_length=50, unique=True)
	product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="skus")
	size = models.CharField(max_length=80)
	retail_price = models.DecimalField(max_digits=10, decimal_places=2)
	cost_price = models.DecimalField(max_digits=10, decimal_places=2)
	weight_ounces = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
	inventory_quantity = models.PositiveIntegerField(default=0)
	low_stock_threshold = models.PositiveIntegerField(default=10)
	is_active = models.BooleanField(default=True)
	barcode_upc = models.CharField(max_length=40, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	objects = SKUQuerySet.as_manager()

	class Meta:
		ordering = ["product__name", "size", "sku_code"]

	def __str__(self) -> str:
		return f"{self.sku_code} ({self.product.name} - {self.size})"

	@property
	def is_low_stock(self) -> bool:
		return self.inventory_quantity <= self.low_stock_threshold

	@property
	def is_purchasable(self) -> bool:
		return self.is_active and self.product.is_active and self.inventory_quantity > 0

	def decrease_inventory(self, quantity: int, *, payment_confirmed: bool = False):
		if quantity <= 0:
			raise ValidationError("Quantity must be greater than zero.")
		if not payment_confirmed:
			raise ValidationError("Inventory can only be reduced after payment confirmation.")
		if self.inventory_quantity < quantity:
			raise ValidationError("Insufficient inventory for this SKU.")

		self.inventory_quantity -= quantity
		self.save(update_fields=["inventory_quantity", "updated_at"])

		if self.is_low_stock:
			try:
				from notifications.alerts import NotificationService
				from notifications.models import StaffAlertEventType

				NotificationService.emit_event(
					event_type=StaffAlertEventType.LOW_PRODUCT_INVENTORY,
					title=f"Low inventory: {self.sku_code}",
					message=f"Remaining: {self.inventory_quantity} (threshold {self.low_stock_threshold})",
					severity="warning",
					sku=self,
					payload={
						"sku_id": self.id,
						"sku_code": self.sku_code,
						"remaining": self.inventory_quantity,
						"threshold": self.low_stock_threshold,
					},
					dedupe_key=f"low_sku:{self.id}:{self.inventory_quantity}",
				)
			except Exception:
				pass


class CSVImportBatchStatus(models.TextChoices):
	PREVIEWED = "previewed", "Previewed"
	COMMITTED = "committed", "Committed"
	ROLLED_BACK = "rolled_back", "Rolled back"
	FAILED = "failed", "Failed"


class CSVImportBatch(models.Model):
	uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="csv_import_batches")
	uploaded_filename = models.CharField(max_length=255)
	status = models.CharField(max_length=20, choices=CSVImportBatchStatus.choices, default=CSVImportBatchStatus.PREVIEWED)
	total_rows = models.PositiveIntegerField(default=0)
	valid_rows = models.PositiveIntegerField(default=0)
	invalid_rows = models.PositiveIntegerField(default=0)
	created_skus = models.PositiveIntegerField(default=0)
	updated_skus = models.PositiveIntegerField(default=0)
	preview_payload = models.JSONField(default=list, blank=True)
	rollback_payload = models.JSONField(default=dict, blank=True)
	uploaded_at = models.DateTimeField(auto_now_add=True)
	committed_at = models.DateTimeField(null=True, blank=True)
	rolled_back_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["-uploaded_at"]

	def __str__(self) -> str:
		return f"CSV batch #{self.pk} by {self.uploader}"


class CSVImportRowError(models.Model):
	batch = models.ForeignKey(CSVImportBatch, on_delete=models.CASCADE, related_name="row_errors")
	row_number = models.PositiveIntegerField()
	sku = models.CharField(max_length=50, blank=True)
	error_message = models.TextField()
	row_data = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["row_number", "id"]

	def __str__(self) -> str:
		return f"Row {self.row_number}: {self.error_message[:80]}"
