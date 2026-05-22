from django.contrib import admin

from .models import Coupon, CouponRedemption


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "percent_off",
        "amount_off_cents",
        "is_active",
        "start_date",
        "end_date",
        "usage_limit",
        "per_customer_limit",
        "applies_to_fundraiser_orders",
        "minimum_cart_subtotal_cents",
    )
    list_filter = ("is_active", "discount_type", "applies_to_fundraiser_orders", "start_date", "end_date")
    search_fields = ("code", "description")
    filter_horizontal = ("applies_to_products", "applies_to_categories")


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("redeemed_at", "coupon", "order", "customer", "discount_cents")
    list_filter = ("coupon", "redeemed_at")
    search_fields = ("coupon__code", "order__order_number", "customer__username", "customer__email")

