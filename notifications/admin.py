from django.contrib import admin

from .models import (
    Notification,
    NotificationDeliveryLog,
    NotificationEvent,
    NotificationPreference,
    OrderNotification,
    StaffAlertPreference,
)


@admin.register(OrderNotification)
class OrderNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "channel", "recipient", "status", "sent_at", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("order__order_number", "recipient")
    readonly_fields = ("created_at",)


@admin.register(StaffAlertPreference)
class StaffAlertPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "enabled", "receive_email", "receive_sms", "receive_internal", "sms_opt_in", "updated_at")
    list_filter = ("enabled", "receive_email", "receive_sms", "receive_internal", "sms_opt_in")
    search_fields = ("user__username", "user__email", "user__phone_number")


@admin.register(NotificationEvent)
class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "severity", "title", "order", "team", "sku", "created_at")
    list_filter = ("event_type", "severity", "created_at")
    search_fields = ("title", "message", "dedupe_key", "order__order_number")
    readonly_fields = ("created_at",)


@admin.register(NotificationDeliveryLog)
class NotificationDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "notification", "user", "channel", "status", "recipient", "sent_at", "read_at", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("recipient", "user__username", "event__title", "notification__title")
    readonly_fields = ("created_at", "sent_at", "read_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "notification_type", "title", "order", "created_at", "read_at")
    list_filter = ("notification_type", "created_at", "read_at")
    search_fields = ("title", "message", "user__username", "user__email", "order__order_number")
    readonly_fields = ("created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "enabled", "receive_in_app", "receive_email", "receive_sms", "sms_opt_in", "updated_at")
    list_filter = ("enabled", "receive_in_app", "receive_email", "receive_sms", "sms_opt_in")
    search_fields = ("user__username", "user__email")
