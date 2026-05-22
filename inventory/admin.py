from django.contrib import admin

from .models import InventoryReservation


@admin.register(InventoryReservation)
class InventoryReservationAdmin(admin.ModelAdmin):
    list_display = ("id", "sku", "quantity", "cart", "order", "expires_at", "released_at", "created_at")
    list_filter = ("created_at",)
    search_fields = ("sku__sku_code",)
    readonly_fields = ("created_at",)
