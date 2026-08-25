"""
Server-side charge orchestration for Poynt Collect checkout.

This module owns the rules that keep a customer from being charged twice:

  1. Every checkout attempt carries a server-issued idempotency key. The key is
     minted when the review page is rendered and stored in the session — the
     browser cannot choose it.
  2. A PaymentTransaction row is claimed for that key BEFORE the provider is
     called. A unique constraint on (provider, idempotency_key) means a second
     concurrent request loses the race and is told the charge is already in
     flight rather than starting another one.
  3. The same key is sent to Poynt as Poynt-Request-Id, so even if a request is
     genuinely replayed at the network level, Poynt returns the original
     transaction instead of charging again.
  4. If the outcome is unknown (timeout / dropped connection) the attempt is
     marked AMBIGUOUS and flagged for reconciliation. It is never retried
     automatically.

The amount charged is always taken from the server-side order total. Nothing
here reads a price from the browser.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from payments.gateways.poynt_auth import (
    PoyntAPIError,
    PoyntAuthError,
    PoyntConfigurationError,
    PoyntTimeoutError,
)
from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentProvider, PaymentStatus, PaymentTransaction

logger = logging.getLogger("payments.checkout")

#: Session key holding the idempotency key for the in-progress checkout.
PAYMENT_INTENT_SESSION_KEY = "payment_intent_key"

#: Shown to customers when the provider declines. Deliberately generic: raw
#: gateway text can leak fraud-screening detail and confuses shoppers.
GENERIC_DECLINE_MESSAGE = (
    "Your card was not approved. Please check your details or try a different card."
)
GENERIC_ERROR_MESSAGE = (
    "We could not reach the payment processor. No charge was made. Please try again."
)
AMBIGUOUS_MESSAGE = (
    "We could not confirm whether your payment completed. Do not retry — our team "
    "is checking with the processor and you will receive an email shortly."
)
IN_FLIGHT_MESSAGE = (
    "A payment for this order is already being processed. Please wait a moment "
    "before trying again."
)


class PaymentAlreadyInFlight(Exception):
    """A charge for this idempotency key is already running or has completed."""

    def __init__(self, message: str, *, transaction_obj: PaymentTransaction | None = None):
        super().__init__(message)
        self.transaction_obj = transaction_obj


class ChargeOutcome:
    """Result of a charge attempt, in terms the view layer can act on."""

    def __init__(
        self,
        *,
        transaction_obj: PaymentTransaction,
        succeeded: bool,
        ambiguous: bool = False,
        customer_message: str = "",
    ):
        self.transaction_obj = transaction_obj
        self.succeeded = succeeded
        self.ambiguous = ambiguous
        self.customer_message = customer_message

    @property
    def payment_result(self) -> dict[str, Any]:
        """Payload consumed by CheckoutService.create_confirmed_order()."""
        tx = self.transaction_obj
        return {
            "provider": tx.provider,
            "status": "captured",
            "provider_ref": tx.provider_transaction_id or "",
            "payment_transaction_id": tx.id,
            "card_brand": tx.card_brand,
            "card_last4": tx.card_last4,
        }


def issue_payment_intent_key(session) -> str:
    """
    Mint (or reuse) the idempotency key for the current checkout attempt.

    Reusing the key across page reloads is deliberate: if the customer refreshes
    the review page and submits again, the same key is presented and the
    duplicate-charge guard recognises the replay.
    """
    existing = session.get(PAYMENT_INTENT_SESSION_KEY)
    if existing:
        return str(existing)
    key = uuid.uuid4().hex
    session[PAYMENT_INTENT_SESSION_KEY] = key
    return key


def clear_payment_intent_key(session) -> None:
    session.pop(PAYMENT_INTENT_SESSION_KEY, None)


def _claim_attempt(
    *,
    provider: str,
    idempotency_key: str,
    amount_cents: int,
    currency: str,
    actor,
    metadata: dict[str, Any],
) -> PaymentTransaction:
    """
    Atomically claim the idempotency key, or raise if it is already claimed.

    Winning this race is what grants the right to call the payment provider.
    """
    try:
        with transaction.atomic():
            return PaymentTransaction.objects.create(
                provider=provider,
                status=PaymentStatus.PENDING,
                order=None,
                created_by=actor,
                amount_cents=amount_cents,
                currency=currency,
                idempotency_key=idempotency_key,
                provider_metadata={"attempt": metadata},
            )
    except IntegrityError:
        existing = PaymentTransaction.objects.filter(
            provider=provider, idempotency_key=idempotency_key
        ).first()

        if existing is None:
            # The unique violation came from somewhere else entirely.
            raise

        if existing.is_confirmed:
            raise PaymentAlreadyInFlight(
                "This payment has already been completed.", transaction_obj=existing
            )
        if existing.status == PaymentStatus.AMBIGUOUS:
            raise PaymentAlreadyInFlight(AMBIGUOUS_MESSAGE, transaction_obj=existing)
        raise PaymentAlreadyInFlight(IN_FLIGHT_MESSAGE, transaction_obj=existing)


def _store_card_details(tx: PaymentTransaction, raw: dict[str, Any]) -> None:
    """Persist PCI-safe card descriptors returned by the provider."""
    details = (raw or {}).get("_card_details") or {}
    if not isinstance(details, dict):
        return
    tx.card_brand = str(details.get("card_brand", ""))[:32]
    tx.card_last4 = str(details.get("card_last4", ""))[:4]
    tx.avs_result = str(details.get("avs_result", ""))[:32]
    tx.cvv_result = str(details.get("cvv_result", ""))[:32]


def _scrub(raw: dict[str, Any] | None) -> dict[str, Any]:
    """
    Drop anything card-like before a provider payload is persisted or logged.

    Poynt does not return a PAN, but this is defence in depth so that a future
    provider-side change cannot silently start storing sensitive fields.
    """
    if not isinstance(raw, dict):
        return {}
    banned = {
        "number", "cardnumber", "pan", "cvv", "cvc", "cvv2", "csc",
        "expirationmonth", "expirationyear", "expiry", "exp", "track1",
        "track2", "pin", "nonce", "cardtoken", "paymenttoken",
    }
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if str(key).lower().replace("_", "") in banned:
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = _scrub(value)
        elif isinstance(value, list):
            cleaned[key] = [_scrub(v) if isinstance(v, dict) else v for v in value]
        else:
            cleaned[key] = value
    return cleaned


def charge_checkout(
    *,
    nonce: str,
    amount_cents: int,
    idempotency_key: str,
    currency: str = "USD",
    provider: str | None = None,
    actor=None,
    request=None,
    receipt_email: str = "",
    metadata: dict[str, Any] | None = None,
) -> ChargeOutcome:
    """
    Charge a Poynt Collect nonce for a server-calculated amount.

    `amount_cents` MUST come from the database-derived order total. This
    function never reads an amount from the request.

    Raises PaymentAlreadyInFlight when the idempotency key is already claimed.
    """
    if amount_cents <= 0:
        raise ValueError("Refusing to charge a non-positive amount.")

    gateway = get_payment_gateway(provider or PaymentProvider.GODADDY)
    safe_metadata = {k: v for k, v in (metadata or {}).items() if k != "guest_email"}

    tx = _claim_attempt(
        provider=gateway.slug,
        idempotency_key=idempotency_key,
        amount_cents=amount_cents,
        currency=currency,
        actor=actor,
        metadata=safe_metadata,
    )

    log_context = {
        "payment_id": tx.id,
        "provider": tx.provider,
        "amount_cents": amount_cents,
        "currency": currency,
        "idempotency_key": idempotency_key,
    }
    logger.info("Charging card via Poynt Collect", extra=log_context)

    try:
        result = gateway.charge_nonce(
            nonce=nonce,
            amount_cents=amount_cents,
            currency=currency,
            idempotency_key=idempotency_key,
            actor=actor,
            request=request,
            email_receipt=bool(receipt_email),
            receipt_email_address=receipt_email,
            metadata=safe_metadata,
        )

    except PoyntTimeoutError as exc:
        # The charge may or may not have been applied. Do NOT retry.
        tx.status = PaymentStatus.AMBIGUOUS
        tx.requires_reconciliation = True
        tx.failure_code = "ambiguous_timeout"
        tx.failure_message = str(exc)[:500]
        tx.save(update_fields=[
            "status", "requires_reconciliation", "failure_code", "failure_message", "updated_at",
        ])
        logger.error("Poynt charge outcome is AMBIGUOUS — flagged for reconciliation", extra=log_context)
        return ChargeOutcome(
            transaction_obj=tx, succeeded=False, ambiguous=True, customer_message=AMBIGUOUS_MESSAGE
        )

    except (PoyntConfigurationError, PoyntAuthError) as exc:
        # We never reached the point of charging — safe to fail closed.
        tx.status = PaymentStatus.FAILED
        tx.failure_code = "configuration_error"
        tx.failure_message = str(exc)[:500]
        tx.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        logger.error("Poynt is misconfigured; no charge attempted", extra=log_context)
        return ChargeOutcome(
            transaction_obj=tx, succeeded=False, customer_message=GENERIC_ERROR_MESSAGE
        )

    except PoyntAPIError as exc:
        tx.status = PaymentStatus.FAILED
        tx.failure_code = f"http_{exc.status_code or 'error'}"[:64]
        tx.failure_message = str(exc)[:500]
        tx.provider_metadata = {**(tx.provider_metadata or {}), "error": _scrub(exc.payload)}
        tx.save(update_fields=[
            "status", "failure_code", "failure_message", "provider_metadata", "updated_at",
        ])
        logger.warning("Poynt rejected the charge", extra={**log_context, "status_code": exc.status_code})
        return ChargeOutcome(
            transaction_obj=tx, succeeded=False, customer_message=GENERIC_DECLINE_MESSAGE
        )

    except Exception as exc:
        # Unknown failures are treated as ambiguous: we cannot prove no charge
        # occurred, so reconciliation must decide.
        tx.status = PaymentStatus.AMBIGUOUS
        tx.requires_reconciliation = True
        tx.failure_code = "unexpected_error"
        tx.failure_message = f"{type(exc).__name__}: {exc}"[:500]
        tx.save(update_fields=[
            "status", "requires_reconciliation", "failure_code", "failure_message", "updated_at",
        ])
        logger.exception("Unexpected error during Poynt charge", extra=log_context)
        return ChargeOutcome(
            transaction_obj=tx, succeeded=False, ambiguous=True, customer_message=AMBIGUOUS_MESSAGE
        )

    # -- provider responded ---------------------------------------------------
    _store_card_details(tx, result.raw or {})
    tx.provider_metadata = {**(tx.provider_metadata or {}), "charge": _scrub(result.raw)}
    tx.provider_transaction_id = (result.provider_transaction_id or "")[:128]

    if result.is_confirmed:
        tx.status = PaymentStatus.CONFIRMED
        tx.confirmed_at = timezone.now()
        tx.failure_code = ""
        tx.failure_message = ""
        tx.save()
        logger.info(
            "Poynt charge approved",
            extra={**log_context, "transaction_id": tx.provider_transaction_id},
        )
        return ChargeOutcome(transaction_obj=tx, succeeded=True)

    tx.status = PaymentStatus.FAILED
    tx.failure_code = (result.failure_code or result.status or "declined")[:64]
    tx.failure_message = (result.failure_message or "")[:500]
    tx.save()
    logger.warning(
        "Poynt charge declined",
        extra={**log_context, "status": result.status, "failure_code": tx.failure_code},
    )
    return ChargeOutcome(
        transaction_obj=tx, succeeded=False, customer_message=GENERIC_DECLINE_MESSAGE
    )


def attach_order(tx: PaymentTransaction, order) -> None:
    """Link a confirmed attempt to the order it paid for."""
    tx.order = order
    tx.save(update_fields=["order", "updated_at"])
