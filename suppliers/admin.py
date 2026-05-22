from django.contrib import admin

from suppliers.models import (
    Supplier,
    SupplierDocument,
    SupplierNote,
    SupplierPerformanceNote,
    SupplierPurchaseOrder,
    SupplierTask,
)
from purchase_orders.models import PurchaseOrder as PurchaseOrderV2


class SupplierNoteInline(admin.TabularInline):
    model = SupplierNote
    extra = 0
    readonly_fields = ("created_at",)


class SupplierTaskInline(admin.TabularInline):
    model = SupplierTask
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class SupplierDocumentInline(admin.TabularInline):
    model = SupplierDocument
    extra = 0
    readonly_fields = ("uploaded_at",)


class SupplierPerformanceInline(admin.TabularInline):
    model = SupplierPerformanceNote
    extra = 0
    readonly_fields = ("created_at",)


class SupplierPurchaseOrderInline(admin.TabularInline):
    model = SupplierPurchaseOrder
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class PurchaseOrderV2Inline(admin.TabularInline):
    model = PurchaseOrderV2
    fk_name = "supplier"
    extra = 0
    readonly_fields = ("created_at", "updated_at", "subtotal_cents", "total_cents")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "status",
        "contact_person",
        "email",
        "phone",
        "average_lead_time_days",
        "rating",
        "last_contact_date",
        "next_follow_up_date",
        "updated_at",
    )
    list_filter = ("category", "status")
    search_fields = ("name", "contact_person", "email", "phone")
    readonly_fields = ("created_at", "updated_at")
    inlines = [
        PurchaseOrderV2Inline,
        SupplierPurchaseOrderInline,
        SupplierTaskInline,
        SupplierNoteInline,
        SupplierPerformanceInline,
        SupplierDocumentInline,
    ]


@admin.register(SupplierTask)
class SupplierTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "title", "status", "due_date", "assigned_to", "updated_at")
    list_filter = ("status", "due_date")
    search_fields = ("title", "supplier__name", "assigned_to__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SupplierNote)
class SupplierNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "created_by", "created_at")
    search_fields = ("supplier__name", "note")
    readonly_fields = ("created_at",)


@admin.register(SupplierDocument)
class SupplierDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "title", "document_type", "uploaded_by", "uploaded_at")
    list_filter = ("document_type", "uploaded_at")
    search_fields = ("supplier__name", "title")
    readonly_fields = ("uploaded_at",)


@admin.register(SupplierPerformanceNote)
class SupplierPerformanceNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "rating_delta", "created_by", "created_at")
    search_fields = ("supplier__name", "note")
    readonly_fields = ("created_at",)


@admin.register(SupplierPurchaseOrder)
class SupplierPurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "po_number", "supplier", "status", "total_cents", "currency", "expected_delivery_date", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("po_number", "supplier__name")
    readonly_fields = ("created_at", "updated_at")
