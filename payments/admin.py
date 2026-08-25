from django.contrib import admin

from payments.models import PaymentEventLog, PaymentRefund, PaymentTransaction


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


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "payment",
        "amount_cents",
        "currency",
        "status",
        "provider_refund_id",
        "issued_by",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("id", "payment__id", "provider_refund_id", "idempotency_key", "reason")
    readonly_fields = ("created_at", "completed_at", "provider_metadata")
