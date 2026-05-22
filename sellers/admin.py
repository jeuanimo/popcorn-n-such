from django.contrib import admin

from .models import SellerLink, SellerStore


@admin.register(SellerLink)
class SellerLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "title", "slug")


@admin.register(SellerStore)
class SellerStoreAdmin(admin.ModelAdmin):
    list_display = ("display_name", "seller", "campaign", "team", "is_active", "created_at")
    list_filter = ("is_active", "campaign")
    search_fields = ("display_name", "seller__username", "slug")
    readonly_fields = ("public_seller_link", "created_at", "updated_at")
    prepopulated_fields = {"slug": ("display_name",)}
