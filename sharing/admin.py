from django.contrib import admin

from .models import QRCode, ShareLink


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "link_type", "token", "campaign", "team", "seller_store", "click_count", "conversion_count", "created_at")
    list_filter = ("link_type", "created_at")
    search_fields = ("token", "campaign__slug", "team__slug", "seller_store__slug")
    readonly_fields = ("click_count", "conversion_count", "last_clicked_at", "last_converted_at", "created_at")


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "share_link", "format", "size", "updated_at")
    search_fields = ("share_link__token",)
    readonly_fields = ("created_at", "updated_at")

