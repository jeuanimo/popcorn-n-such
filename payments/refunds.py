"""
Issuing refunds against completed GoDaddy Payments charges.

Rules enforced here:

  * Only staff may issue a refund.
  * There must be an existing, confirmed payment with a provider transaction id.
  * The total refunded can never exceed the amount originally captured.
  * The original PaymentTransaction is never deleted or overwritten. Each refund
    is its own PaymentRefund row referencing it.
  * Refunds are idempotent: the key is sent as Poynt-Request-Id, so a retried
    request returns the original refund rather than issuing a second one.
"""

from __future__ import annotations

import logging
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from payments.gateways.poynt_auth import PoyntAPIError, PoyntTimeoutError
from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentRefund, PaymentStatus, PaymentTransaction
from payments.signals import payment_refunded
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

logger = logging.getLogger("payments.refunds")


class RefundError(Exception):
    """A refund could not be issued."""


class RefundNotPermitted(RefundError):
    """The actor is not allowed to issue this refund."""


def refundable_amount_cents(payment: PaymentTransaction) -> int:
    """How much of this payment has not yet been refunded."""
    already = sum(
        refund.amount_cents
        for refund in payment.refunds.all()
        if refund.status in {PaymentStatus.REFUNDED, PaymentStatus.PENDING}
    )
    return max(0, payment.amount_cents - already)


def _require_staff(actor) -> None:
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise RefundNotPermitted("You must be signed in to issue a refund.")
    if not (getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False)):
        raise RefundNotPermitted("Only staff may issue refunds.")


def issue_refund(
    *,
    payment: PaymentTransaction,
    actor,
    amount_cents: int | None = None,
    reason: str = "",
    request=None,
    idempotency_key: str | None = None,
) -> PaymentRefund:
    """
    Refund all or part of a confirmed payment.

    `amount_cents=None` refunds the full remaining amount.
    """
    _require_staff(actor)

    if not payment.is_confirmed:
        raise RefundError("Only a confirmed payment can be refunded.")
    if not payment.provider_transaction_id:
        raise RefundError(
            "This payment has no processor transaction id, so it cannot be refunded automatically."
        )

    remaining = refundable_amount_cents(payment)
    if remaining <= 0:
        raise RefundError("This payment has already been fully refunded.")

    requested = int(amount_cents) if amount_cents is not None else remaining
    if requested <= 0:
        raise RefundError("Refund amount must be greater than zero.")
    if requested > remaining:
        raise RefundError(
            f"Refund of {requested}¢ exceeds the {remaining}¢ still available on this payment."
        )

    key = idempotency_key or uuid.uuid4().hex

    try:
        with transaction.atomic():
            refund = PaymentRefund.objects.create(
                payment=payment,
                amount_cents=requested,
                currency=payment.currency,
                status=PaymentStatus.PENDING,
                idempotency_key=key,
                reason=reason[:255],
                issued_by=actor,
            )
    except IntegrityError as exc:
        raise RefundError("A refund with this key has already been issued.") from exc

    gateway = get_payment_gateway(payment.provider)
    log_context = {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        "transaction_id": payment.provider_transaction_id,
        "amount_cents": requested,
        "idempotency_key": key,
    }
    logger.info("Issuing refund", extra=log_context)

    try:
        result = gateway.refund_transaction(
            provider_transaction_id=payment.provider_transaction_id,
            # A full refund omits amounts entirely, which is what the provider
            # expects and avoids rounding disputes on the final refund.
            amount_cents=None if requested == payment.amount_cents else requested,
            currency=payment.currency,
            idempotency_key=key,
            actor=actor,
            request=request,
        )
    except PoyntTimeoutError as exc:
        # Unknown outcome. Leave the row PENDING so it is visible and is not
        # silently retried into a double refund.
        refund.failure_code = "ambiguous_timeout"
        refund.failure_message = str(exc)[:500]
        refund.save(update_fields=["failure_code", "failure_message"])
        logger.error("Refund outcome is ambiguous — verify at the processor", extra=log_context)
        raise RefundError(
            "The refund request timed out and its outcome is unknown. "
            "Check the processor before retrying — do not issue a second refund."
        ) from exc
    except PoyntAPIError as exc:
        refund.status = PaymentStatus.FAILED
        refund.failure_code = f"http_{exc.status_code or 'error'}"[:64]
        refund.failure_message = str(exc)[:500]
        refund.save(update_fields=["status", "failure_code", "failure_message"])
        logger.warning("Refund rejected by processor", extra=log_context)
        raise RefundError(f"The processor rejected the refund: {exc}") from exc

    refund.provider_refund_id = (result.provider_refund_id or "")[:128]
    refund.provider_metadata = result.raw or {}

    if result.status == "refunded":
        refund.status = PaymentStatus.REFUNDED
        refund.completed_at = timezone.now()
        refund.save()

        # Mark the payment refunded only once nothing is left on it.
        if refundable_amount_cents(payment) <= 0:
            payment.status = PaymentStatus.REFUNDED
            payment.save(update_fields=["status", "updated_at"])

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="Refund issued",
            actor=actor,
            request=request,
            metadata={
                "provider": payment.provider,
                "order_id": payment.order_id,
                "payment_transaction_id": payment.id,
                "refund_id": refund.id,
                "amount_cents": requested,
                "reason": reason[:255],
            },
        )
        payment_refunded.send(
            sender=PaymentTransaction,
            payment_transaction_id=payment.id,
            order_id=payment.order_id,
            provider=payment.provider,
            amount_cents=requested,
            currency=payment.currency,
        )
        logger.info("Refund completed", extra={**log_context, "refund_id": refund.id})
        return refund

    refund.status = PaymentStatus.FAILED
    refund.failure_code = (result.failure_code or result.status or "refund_failed")[:64]
    refund.failure_message = (result.failure_message or "")[:500]
    refund.save()
    raise RefundError("The refund was not completed by the processor.")
