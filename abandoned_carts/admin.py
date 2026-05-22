from django.contrib import admin

from .models import AbandonedCartEvent, CartRecoveryMessage, CartRecoveryToken


class CartRecoveryMessageInline(admin.TabularInline):
	model = CartRecoveryMessage
	extra = 0
	readonly_fields = ("channel", "stage", "status", "to_value", "created_at", "sent_at")


@admin.register(AbandonedCartEvent)
class AbandonedCartEventAdmin(admin.ModelAdmin):
	list_display = (
		"id",
		"cart",
		"customer_email",
		"sms_consent",
		"recovered",
		"is_closed",
		"close_reason",
		"updated_at",
	)
	list_filter = ("sms_consent", "recovered", "is_closed", "close_reason")
	search_fields = ("customer_email", "customer_phone", "cart__id", "cart__user__username")
	inlines = [CartRecoveryMessageInline]


@admin.register(CartRecoveryToken)
class CartRecoveryTokenAdmin(admin.ModelAdmin):
	list_display = ("id", "cart", "purpose", "expires_at", "used_at", "revoked_at")
	list_filter = ("purpose",)
	search_fields = ("cart__id", "event__id", "token_hash")


@admin.register(CartRecoveryMessage)
class CartRecoveryMessageAdmin(admin.ModelAdmin):
	list_display = ("id", "event", "channel", "stage", "status", "to_value", "sent_at")
	list_filter = ("channel", "stage", "status")
	search_fields = ("to_value", "event__id", "event__cart__id")
