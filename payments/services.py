from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentEventLog, PaymentStatus, PaymentTransaction
from payments.signals import payment_confirmed, payment_failed, payment_refunded
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def record_payment_event(
    *,
    provider: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    signature_valid: bool = False,
    transaction_obj: PaymentTransaction | None = None,
    external_event_id: str = "",
    request_id: str = "",
) -> PaymentEventLog:
    return PaymentEventLog.objects.create(
        provider=provider,
        event_type=event_type,
        payload=payload or {},
        headers=headers or {},
        signature_valid=signature_valid,
        transaction=transaction_obj,
        external_event_id=external_event_id,
        request_id=request_id,
    )


@transaction.atomic
def create_payment_session(
    *,
    order,
    provider: str | None = None,
    amount_cents: int | None = None,
    currency: str = "USD",
    actor=None,
    request=None,
    return_url: str | None = None,
    cancel_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PaymentTransaction:
    gateway = get_payment_gateway(provider)
    idempotency_key = uuid.uuid4().hex
    amount = int(amount_cents if amount_cents is not None else getattr(order, "total_cents"))

    tx = PaymentTransaction.objects.create(
        provider=gateway.slug,
        status=PaymentStatus.CREATED,
        order=order,
        created_by=getattr(order, "customer", None) if actor is None else actor,
        amount_cents=amount,
        currency=currency,
        idempotency_key=idempotency_key,
        provider_metadata=metadata or {},
    )

    session = gateway.create_payment_session(
        order_id=order.id,
        amount_cents=amount,
        currency=currency,
        idempotency_key=idempotency_key,
        return_url=return_url,
        cancel_url=cancel_url,
        actor=actor,
        request=request,
        metadata=metadata,
    )
    tx.provider_session_id = session.provider_session_id or ""
    tx.provider_transaction_id = session.provider_transaction_id or ""
    tx.checkout_url = session.checkout_url or ""
    if session.raw:
        tx.provider_metadata = {**(tx.provider_metadata or {}), **{"create_session": session.raw}}
    tx.status = PaymentStatus.PENDING if tx.checkout_url else PaymentStatus.CREATED
    tx.save(update_fields=["provider_session_id", "provider_transaction_id", "checkout_url", "provider_metadata", "status"])

    log_audit_event(
        action=AuditAction.PAYMENT_EVENT,
        message="Payment session created",
        actor=actor,
        request=request,
        metadata={
            "provider": tx.provider,
            "order_id": tx.order_id,
            "payment_transaction_id": tx.id,
            "amount_cents": tx.amount_cents,
            "currency": tx.currency,
        },
    )
    return tx


@transaction.atomic
def verify_payment(*, payment_transaction: PaymentTransaction, actor=None, request=None) -> PaymentTransaction:
    gateway = get_payment_gateway(payment_transaction.provider)
    result = gateway.verify_payment(
        provider_transaction_id=payment_transaction.provider_transaction_id or None,
        provider_session_id=payment_transaction.provider_session_id or None,
        actor=actor,
        request=request,
    )
    payment_transaction.provider_metadata = {
        **(payment_transaction.provider_metadata or {}),
        "verify": result.raw or {"status": result.status},
    }
    if result.provider_transaction_id and not payment_transaction.provider_transaction_id:
        payment_transaction.provider_transaction_id = result.provider_transaction_id

    if result.is_confirmed:
        return handle_payment_success(payment_transaction=payment_transaction, actor=actor, request=request)

    if result.status in {"failed", "canceled", "cancelled"}:
        return handle_payment_failure(
            payment_transaction=payment_transaction,
            failure_code=result.failure_code or "",
            failure_message=result.failure_message or "",
            actor=actor,
            request=request,
        )

    payment_transaction.status = PaymentStatus.PENDING
    payment_transaction.save(update_fields=["provider_metadata", "provider_transaction_id", "status", "updated_at"])
    return payment_transaction


@transaction.atomic
def handle_payment_success(*, payment_transaction: PaymentTransaction, actor=None, request=None) -> PaymentTransaction:
    if payment_transaction.status == PaymentStatus.CONFIRMED:
        return payment_transaction

    payment_transaction.status = PaymentStatus.CONFIRMED
    payment_transaction.confirmed_at = timezone.now()
    payment_transaction.failure_code = ""
    payment_transaction.failure_message = ""
    payment_transaction.save(update_fields=["status", "confirmed_at", "failure_code", "failure_message", "updated_at"])

    log_audit_event(
        action=AuditAction.PAYMENT_EVENT,
        message="Payment confirmed",
        actor=actor,
        request=request,
        metadata={
            "provider": payment_transaction.provider,
            "order_id": payment_transaction.order_id,
            "payment_transaction_id": payment_transaction.id,
        },
    )

    payment_confirmed.send(
        sender=PaymentTransaction,
        payment_transaction_id=payment_transaction.id,
        order_id=payment_transaction.order_id,
        provider=payment_transaction.provider,
        amount_cents=payment_transaction.amount_cents,
        currency=payment_transaction.currency,
    )
    return payment_transaction


@transaction.atomic
def handle_payment_failure(
    *,
    payment_transaction: PaymentTransaction,
    failure_code: str = "",
    failure_message: str = "",
    actor=None,
    request=None,
) -> PaymentTransaction:
    payment_transaction.status = PaymentStatus.FAILED
    payment_transaction.failure_code = failure_code
    payment_transaction.failure_message = failure_message
    payment_transaction.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])

    log_audit_event(
        action=AuditAction.PAYMENT_EVENT,
        message="Payment failed",
        actor=actor,
        request=request,
        metadata={
            "provider": payment_transaction.provider,
            "order_id": payment_transaction.order_id,
            "payment_transaction_id": payment_transaction.id,
            "failure_code": failure_code,
        },
    )

    payment_failed.send(
        sender=PaymentTransaction,
        payment_transaction_id=payment_transaction.id,
        order_id=payment_transaction.order_id,
        provider=payment_transaction.provider,
        amount_cents=payment_transaction.amount_cents,
        currency=payment_transaction.currency,
        failure_code=failure_code,
    )
    return payment_transaction


@transaction.atomic
def refund_payment(
    *,
    payment_transaction: PaymentTransaction,
    amount_cents: int | None = None,
    actor=None,
    request=None,
    metadata: dict[str, Any] | None = None,
) -> PaymentTransaction:
    if not payment_transaction.provider_transaction_id:
        raise ValueError("Cannot refund without provider_transaction_id.")

    gateway = get_payment_gateway(payment_transaction.provider)
    result = gateway.refund_payment(
        provider_transaction_id=payment_transaction.provider_transaction_id,
        amount_cents=amount_cents,
        currency=payment_transaction.currency,
        idempotency_key=uuid.uuid4().hex,
        actor=actor,
        request=request,
        metadata=metadata,
    )

    payment_transaction.provider_metadata = {
        **(payment_transaction.provider_metadata or {}),
        "refund": result.raw or {"status": result.status},
    }
    if result.status in {"succeeded", "success", "refunded"}:
        payment_transaction.status = PaymentStatus.REFUNDED
    payment_transaction.save(update_fields=["provider_metadata", "status", "updated_at"])

    payment_refunded.send(
        sender=PaymentTransaction,
        payment_transaction_id=payment_transaction.id,
        order_id=payment_transaction.order_id,
        provider=payment_transaction.provider,
        amount_cents=payment_transaction.amount_cents,
        currency=payment_transaction.currency,
    )
    return payment_transaction

