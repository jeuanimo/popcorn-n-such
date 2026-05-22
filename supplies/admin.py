from django.contrib import admin

from supplies.models import Supply


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
	list_display = ("name", "category", "unit", "inventory_quantity", "low_stock_threshold", "is_active", "updated_at")
	list_filter = ("category", "is_active")
	search_fields = ("name", "sku_code")
	readonly_fields = ("created_at", "updated_at")
