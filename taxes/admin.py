from django.contrib import admin

from taxes.models import TaxCalculation


@admin.register(TaxCalculation)
class TaxCalculationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "order",
        "cart",
        "taxable_subtotal_cents",
        "shipping_cents",
        "tax_cents",
        "currency",
        "succeeded",
        "is_final",
        "calculated_at",
    )
    list_filter = ("provider", "succeeded", "is_final", "currency", "calculated_at")
    search_fields = ("id", "order__id", "cart__id", "provider_reference_id", "shipping_postal_code")
    readonly_fields = ("calculated_at",)
