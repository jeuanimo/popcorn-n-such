from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import AddressValidation, PackageTemplate, ShippingLabel, ShippingRate


@admin.register(PackageTemplate)
class PackageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "weight_oz", "length_in", "width_in", "height_in", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(AddressValidation)
class AddressValidationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "order", "provider", "raw_address_line_1", "raw_city", "raw_state",
        "is_valid", "is_corrected", "validated_at",
    )
    list_filter = ("provider", "is_valid", "is_corrected", "validated_at")
    search_fields = ("order__order_number", "raw_address_line_1", "raw_city", "raw_postal_code")
    readonly_fields = (
        "order", "provider", "raw_recipient_name", "raw_address_line_1", "raw_address_line_2",
        "raw_city", "raw_state", "raw_postal_code", "raw_country",
        "validated_address_line_1", "validated_address_line_2", "validated_city",
        "validated_state", "validated_postal_code", "validated_country",
        "is_valid", "is_corrected", "failure_reason", "raw_response",
        "validated_by", "validated_at",
    )


@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    list_display = (
        "id", "order", "provider", "carrier", "service_name",
        "rate_display", "estimated_delivery_days", "is_selected", "fetched_at",
    )
    list_filter = ("provider", "carrier", "is_selected", "fetched_at")
    search_fields = ("order__order_number", "tracking_number", "provider_rate_id")
    readonly_fields = (
        "order", "provider", "carrier", "service_name", "service_code",
        "rate_cents", "currency", "estimated_delivery_days", "provider_rate_id",
        "raw_response", "fetched_at",
    )

    @admin.display(description="Rate")
    def rate_display(self, obj: ShippingRate) -> str:
        return f"${obj.rate_cents / 100:.2f} {obj.currency}"


@admin.register(ShippingLabel)
class ShippingLabelAdmin(admin.ModelAdmin):
    list_display = (
        "id", "order", "provider", "carrier", "service_name",
        "tracking_number", "label_format", "is_voided", "reprint_count", "created_at",
    )
    list_filter = ("provider", "carrier", "label_format", "is_voided", "created_at")
    search_fields = ("order__order_number", "tracking_number", "provider_label_id")
    readonly_fields = (
        "order", "rate", "provider", "carrier", "service_name",
        "tracking_number", "tracking_url_link", "label_format", "label_download_link", "label_url", "label_file",
        "rate_cents", "provider_label_id", "raw_response",
        "is_voided", "voided_at", "voided_by",
        "reprint_count", "created_by", "created_at",
    )
    actions = ["reprint_label_action"]

    @admin.display(description="Tracking URL")
    def tracking_url_link(self, obj: ShippingLabel) -> str:
        if obj.tracking_url:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.tracking_url, obj.tracking_number)
        return obj.tracking_number

    @admin.display(description="Label download")
    def label_download_link(self, obj: ShippingLabel) -> str:
        url = reverse("shipping:label-download", kwargs={"label_id": obj.id})
        return format_html('<a href="{}" target="_blank">Download</a>', url)

    @admin.action(description="Record reprint for selected labels")
    def reprint_label_action(self, request, queryset):
        from .services import ShippingService

        count = 0
        for label in queryset.select_related("order"):
            provider_service = ShippingService(provider=label.provider)
            provider_service.record_reprint(label, actor=request.user, request=request)
            count += 1
        self.message_user(request, f"Recorded reprint for {count} label(s).")
