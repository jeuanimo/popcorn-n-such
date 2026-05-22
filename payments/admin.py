from django.contrib import admin

from payments.models import PaymentEventLog, PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "status",
        "order",
        "amount_cents",
        "currency",
        "provider_transaction_id",
        "provider_session_id",
        "confirmed_at",
        "created_at",
    )
    list_filter = ("provider", "status", "currency", "created_at")
    search_fields = ("id", "order__id", "provider_transaction_id", "provider_session_id", "idempotency_key")
    readonly_fields = ("created_at", "updated_at", "confirmed_at")


@admin.register(PaymentEventLog)
class PaymentEventLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "event_type",
        "external_event_id",
        "transaction",
        "signature_valid",
        "received_at",
        "processed_at",
    )
    list_filter = ("provider", "signature_valid", "event_type", "received_at")
    search_fields = ("id", "external_event_id", "transaction__id", "request_id")
    readonly_fields = ("received_at", "processed_at")
