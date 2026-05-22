from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.utils import timezone

from .models import Order, OrderItem, OrderStatus


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product_name_snapshot", "sku_snapshot", "line_total_cents", "weight_ounces")


# ---------------------------------------------------------------------------
# Fulfillment admin actions
# ---------------------------------------------------------------------------

@admin.action(description="1. Validate shipping address")
def validate_address_action(modeladmin, request, queryset):
    from shipping.services import AddressData, ShippingService

    svc = ShippingService()
    ok = err = 0
    for order in queryset.select_related("customer"):
        try:
            addr = AddressData(
                recipient_name=order.shipping_recipient_name,
                address_line_1=order.shipping_address_line_1,
                address_line_2=order.shipping_address_line_2 or "",
                city=order.shipping_city,
                state=order.shipping_state,
                postal_code=order.shipping_postal_code,
                country=order.shipping_country,
            )
            result = svc.validate_address(order, addr, actor=request.user, request=request)
            if result.is_valid:
                ok += 1
            else:
                err += 1
        except Exception:
            err += 1
    modeladmin.message_user(request, f"Address validation: {ok} valid, {err} invalid/failed.")


@admin.action(description="2. Fetch shipping rates")
def get_rates_action(modeladmin, request, queryset):
    from shipping.carriers.base import PackageInput
    from shipping.services import ShippingService

    from_postal = getattr(settings, "SHIPPING_FROM_POSTAL_CODE", "00000")
    from_country = getattr(settings, "SHIPPING_FROM_COUNTRY", "US")
    default_weight_oz = getattr(settings, "SHIPPING_DEFAULT_WEIGHT_OZ", 16)
    svc = ShippingService()
    total = 0
    for order in queryset:
        pkg = PackageInput(
            weight_oz=float(default_weight_oz),
            length_in=12.0,
            width_in=9.0,
            height_in=4.0,
        )
        svc.get_rates(order, from_postal, pkg, actor=request.user, request=request, from_country=from_country)
        total += 1
    modeladmin.message_user(request, f"Fetched rates for {total} order(s).")


@admin.action(description="3. Create shipping label (cheapest available rate)")
def create_label_action(modeladmin, request, queryset):
    from shipping.carriers.base import PackageInput
    from shipping.models import ShippingRate
    from shipping.services import AddressData, ShippingService

    from_postal = getattr(settings, "SHIPPING_FROM_POSTAL_CODE", "00000")
    default_weight_oz = getattr(settings, "SHIPPING_DEFAULT_WEIGHT_OZ", 16)
    from_name = getattr(settings, "SHIPPING_FROM_NAME", "Popcorn N Such")
    from_addr1 = getattr(settings, "SHIPPING_FROM_ADDRESS_LINE_1", "")
    from_city = getattr(settings, "SHIPPING_FROM_CITY", "")
    from_state = getattr(settings, "SHIPPING_FROM_STATE", "")
    from_country = getattr(settings, "SHIPPING_FROM_COUNTRY", "US")

    from_address = AddressData(
        recipient_name=from_name,
        address_line_1=from_addr1,
        city=from_city,
        state=from_state,
        postal_code=from_postal,
        country=from_country,
    )
    ok = err = skipped = 0
    for order in queryset:
        rate = ShippingRate.objects.filter(order=order, is_selected=False).order_by("rate_cents").first()
        if rate is None:
            skipped += 1
            continue
        try:
            svc = ShippingService(provider=rate.provider)
            pkg = PackageInput(
                weight_oz=float(default_weight_oz),
                length_in=12.0,
                width_in=9.0,
                height_in=4.0,
            )
            svc.create_label(order, rate, from_address, pkg, actor=request.user, request=request)
            ok += 1
        except Exception:
            err += 1
    modeladmin.message_user(
        request,
        f"Labels created: {ok}. Skipped (no rates): {skipped}. Failed: {err}.",
    )


@admin.action(description="4. Mark as packed")
def mark_packed_action(modeladmin, request, queryset):
    from fulfillment.models import FulfillmentRecord, FulfillmentStatus

    updated = 0
    for order in queryset.filter(status=OrderStatus.PROCESSING):
        order.status = OrderStatus.PACKED
        order.save(update_fields=["status", "updated_at"])
        FulfillmentRecord.objects.filter(order=order).update(
            status=FulfillmentStatus.PACKED,
            updated_at=timezone.now(),
        )
        updated += 1
    modeladmin.message_user(request, f"Marked {updated} order(s) as packed.")


@admin.action(description="5. Mark as shipped")
def mark_shipped_action(modeladmin, request, queryset):
    from fulfillment.models import FulfillmentRecord, FulfillmentStatus
    from shipping.models import ShippingLabel

    updated = 0
    for order in queryset.filter(status__in=[OrderStatus.PROCESSING, OrderStatus.PACKED]):
        label = ShippingLabel.objects.filter(order=order, is_voided=False).order_by("-created_at").first()
        tracking = label.tracking_number if label else ""
        carrier = label.carrier if label else ""

        order.status = OrderStatus.SHIPPED
        order.save(update_fields=["status", "updated_at"])
        FulfillmentRecord.objects.filter(order=order).update(
            status=FulfillmentStatus.SHIPPED,
            tracking_number=tracking,
            carrier=carrier,
            updated_at=timezone.now(),
        )
        updated += 1
    modeladmin.message_user(request, f"Marked {updated} order(s) as shipped.")


@admin.action(description="6. Resend tracking email")
def resend_tracking_email_action(modeladmin, request, queryset):
    from notifications.dispatch import send_tracking_email_for_order
    from shipping.models import ShippingLabel

    sent = skipped = 0
    for order in queryset:
        label = ShippingLabel.objects.filter(order=order, is_voided=False).order_by("-created_at").first()
        if not label:
            skipped += 1
            continue
        result = send_tracking_email_for_order(order=order, label=label, actor=request.user, django_request=request)
        if result:
            sent += 1
        else:
            skipped += 1
    modeladmin.message_user(request, f"Tracking email sent for {sent} order(s). Skipped: {skipped}.")


@admin.action(description="3b. Print/download latest label (records reprint)")
def print_label_action(modeladmin, request, queryset):
    from shipping.models import ShippingLabel
    from shipping.services import ShippingService

    if queryset.count() != 1:
        modeladmin.message_user(request, "Select exactly 1 order to print/download its label.", level="warning")
        return

    order = queryset.first()
    label = ShippingLabel.objects.filter(order=order, is_voided=False).order_by("-created_at").first()
    if not label:
        modeladmin.message_user(request, "No active label found for this order.", level="warning")
        return

    ShippingService(provider=label.provider).record_reprint(label, actor=request.user, request=request)
    return HttpResponseRedirect(f"/shipping/labels/{label.id}/download/")


# ---------------------------------------------------------------------------
# Admin registrations
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number", "customer", "guest_email", "status", "payment_status",
        "fundraiser_campaign", "team", "total_cents", "created_at",
    )
    list_filter = ("status", "payment_status", "fundraiser_campaign", "created_at")
    search_fields = ("order_number", "customer__username", "guest_email", "fundraiser_code")
    readonly_fields = ("order_number", "created_at", "updated_at")
    inlines = [OrderItemInline]
    actions = [
        validate_address_action,
        get_rates_action,
        create_label_action,
        print_label_action,
        mark_packed_action,
        mark_shipped_action,
        resend_tracking_email_action,
    ]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product_name_snapshot", "sku", "quantity", "unit_price_cents", "line_total_cents")
    search_fields = ("order__order_number", "sku__sku_code", "product_name_snapshot")
    readonly_fields = ("product_name_snapshot", "sku_snapshot")
