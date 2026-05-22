from django.contrib import admin

from .models import CSVImportBatch, CSVImportRowError, Product, ProductCategory, SKU


class SKUInline(admin.TabularInline):
	model = SKU
	extra = 0
	fields = (
		"sku_code",
		"size",
		"retail_price",
		"inventory_quantity",
		"low_stock_threshold",
		"is_active",
	)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = (
		"name",
		"category",
		"flavor",
		"is_active",
		"is_featured",
		"fundraiser_eligible",
		"standalone_store_eligible",
	)
	list_filter = (
		"category",
		"is_active",
		"is_featured",
		"fundraiser_eligible",
		"standalone_store_eligible",
	)
	search_fields = ("name", "slug", "flavor")
	prepopulated_fields = {"slug": ("name",)}
	inlines = [SKUInline]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
	list_display = ("name", "key", "is_active")
	list_filter = ("is_active",)
	search_fields = ("name", "key")


@admin.register(SKU)
class SKUAdmin(admin.ModelAdmin):
	list_display = (
		"sku_code",
		"product",
		"size",
		"retail_price",
		"inventory_quantity",
		"low_stock_threshold",
		"is_low_stock",
		"is_active",
	)
	list_filter = ("is_active", "product__category")
	search_fields = ("sku_code", "product__name", "barcode_upc")


class CSVImportRowErrorInline(admin.TabularInline):
	model = CSVImportRowError
	extra = 0
	can_delete = False
	readonly_fields = ("row_number", "sku", "error_message", "created_at")
	fields = ("row_number", "sku", "error_message", "created_at")


@admin.register(CSVImportBatch)
class CSVImportBatchAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"uploader",
		"uploaded_filename",
		"status",
		"total_rows",
		"valid_rows",
		"invalid_rows",
		"created_skus",
		"updated_skus",
		"uploaded_at",
	)
	list_filter = ("status", "uploaded_at")
	search_fields = ("uploaded_filename", "uploader__username", "uploader__email")
	readonly_fields = (
		"uploader",
		"uploaded_filename",
		"status",
		"total_rows",
		"valid_rows",
		"invalid_rows",
		"created_skus",
		"updated_skus",
		"preview_payload",
		"rollback_payload",
		"uploaded_at",
		"committed_at",
		"rolled_back_at",
	)
	inlines = [CSVImportRowErrorInline]

	def has_add_permission(self, request):
		return False


@admin.register(CSVImportRowError)
class CSVImportRowErrorAdmin(admin.ModelAdmin):
	list_display = ("batch", "row_number", "sku", "created_at")
	search_fields = ("sku", "error_message", "batch__uploaded_filename")
	readonly_fields = ("batch", "row_number", "sku", "error_message", "row_data", "created_at")

	def has_add_permission(self, request):
		return False
