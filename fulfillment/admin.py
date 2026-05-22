from django.contrib import admin

from .models import FulfillmentRecord


@admin.register(FulfillmentRecord)
class FulfillmentRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "warehouse_code", "tracking_number", "queued_at", "updated_at")
    list_filter = ("status", "queued_at")
    search_fields = ("order__order_number", "tracking_number")
    readonly_fields = ("queued_at",)
