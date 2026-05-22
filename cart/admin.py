from django.contrib import admin

from .models import Cart, CartAttribution, CartItem, SavedForLaterItem


class CartItemInline(admin.TabularInline):
	model = CartItem
	extra = 0


class SavedForLaterInline(admin.TabularInline):
	model = SavedForLaterItem
	extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "session_key", "is_active", "updated_at")
	list_filter = ("is_active", "updated_at")
	search_fields = ("user__username", "session_key")
	inlines = [CartItemInline, SavedForLaterInline]


@admin.register(CartAttribution)
class CartAttributionAdmin(admin.ModelAdmin):
	list_display = ("cart", "fundraiser_campaign", "team", "seller", "updated_at")
	search_fields = ("fundraiser_campaign", "team", "seller", "cart__user__username")
