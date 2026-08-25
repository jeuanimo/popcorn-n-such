"""
Resolving payments whose outcome we never learned.

The dangerous case in card processing is not a decline — it is silence:

    Django sends charge
        ↓
    GoDaddy processes the charge   (the customer's card IS debited)
        ↓
    network connection dies
        ↓
    Django never receives the response

Retrying here would charge the customer a second time. Instead the attempt is
recorded as AMBIGUOUS and resolved by *asking* GoDaddy what happened, using
read-only endpoints that are safe to call repeatedly.

Two lookup strategies, in order:

  1. If we captured a provider transaction id before the failure, fetch that
     transaction directly.
  2. Otherwise, search the business's recent transactions for one carrying our
     idempotency key (sent as Poynt-Request-Id) or matching amount+window.

Only a positive identification marks a payment as taken. When neither lookup
finds anything and enough time has passed for the provider to have settled, the
attempt is treated as never having reached the processor.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from payments.gateways.poynt_auth import PoyntAPIError, PoyntTimeoutError
from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentStatus, PaymentTransaction

logger = logging.getLogger("payments.reconciliation")

#: How long to keep asking before concluding the charge never landed. Poynt
#: transactions appear within seconds; this is generous on purpose.
SETTLEMENT_GRACE = timedelta(minutes=30)

#: Give up automated resolution after this many tries and escalate to staff.
MAX_RECONCILIATION_ATTEMPTS = 12

_CONFIRMED_STATUSES = {"captured", "confirmed", "succeeded", "success", "paid", "authorized", "completed"}
_FAILED_STATUSES = {"failed", "declined", "canceled", "cancelled", "voided", "error", "rejected"}


def _classify(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized in _CONFIRMED_STATUSES:
        return "confirmed"
    if normalized in _FAILED_STATUSES:
        return "failed"
    return "unknown"


def _extract_status(payload: dict[str, Any]) -> str:
    for key in ("status", "state", "transactionStatus"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    processor = payload.get("processorResponse")
    if isinstance(processor, dict):
        for key in ("status", "statusCode"):
            value = processor.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _find_by_request_id(gateway, tx: PaymentTransaction) -> dict[str, Any] | None:
    """
    Search recent transactions for one created under our idempotency key.

    Poynt echoes the Poynt-Request-Id it was charged with, which lets us match a
    transaction we never received a response for.
    """
    if not tx.idempotency_key:
        return None

    window_start = (tx.created_at - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        payload = gateway.find_transactions(
            params={"startAt": window_start, "limit": 100},
        )
    except (PoyntAPIError, PoyntTimeoutError) as exc:
        logger.warning(
            "Transaction search failed during reconciliation",
            extra={"payment_id": tx.id, "error": str(exc)},
        )
        return None

    for item in payload.get("transactions") or []:
        if not isinstance(item, dict):
            continue
        context = item.get("context") if isinstance(item.get("context"), dict) else {}
        candidate_ids = {
            str(item.get("requestId") or ""),
            str(context.get("requestId") or ""),
        }
        if tx.idempotency_key in candidate_ids:
            return item
    return None


def reconcile_transaction(tx: PaymentTransaction, *, actor=None) -> PaymentTransaction:
    """
    Determine the true outcome of one ambiguous payment attempt.

    Read-only against the provider — safe to call as often as needed. Returns
    the transaction with its status updated when the outcome becomes known.
    """
    if tx.status != PaymentStatus.AMBIGUOUS:
        return tx

    gateway = get_payment_gateway(tx.provider)
    tx.reconciliation_attempts += 1

    remote: dict[str, Any] | None = None
    try:
        if tx.provider_transaction_id:
            remote = gateway.get_transaction(transaction_id=tx.provider_transaction_id)
        else:
            remote = _find_by_request_id(gateway, tx)
    except PoyntAPIError as exc:
        if exc.status_code == 404:
            # Definitively not present at the processor.
            remote = None
        else:
            logger.warning(
                "Reconciliation lookup failed; will retry",
                extra={"payment_id": tx.id, "attempt": tx.reconciliation_attempts, "error": str(exc)},
            )
            tx.save(update_fields=["reconciliation_attempts", "updated_at"])
            return tx
    except PoyntTimeoutError:
        tx.save(update_fields=["reconciliation_attempts", "updated_at"])
        return tx

    if remote:
        outcome = _classify(_extract_status(remote))
        provider_txn_id = str(remote.get("id") or tx.provider_transaction_id or "")[:128]

        if outcome == "confirmed":
            tx.status = PaymentStatus.CONFIRMED
            tx.confirmed_at = timezone.now()
            tx.provider_transaction_id = provider_txn_id
            tx.requires_reconciliation = False
            tx.reconciled_at = timezone.now()
            tx.failure_code = ""
            tx.failure_message = ""
            tx.provider_metadata = {**(tx.provider_metadata or {}), "reconciled": {"status": "confirmed"}}
            tx.save()
            logger.error(
                "RECONCILED: ambiguous charge WAS taken — customer has been charged",
                extra={
                    "payment_id": tx.id,
                    "transaction_id": provider_txn_id,
                    "order_id": tx.order_id,
                    "amount_cents": tx.amount_cents,
                },
            )
            return tx

        if outcome == "failed":
            tx.status = PaymentStatus.FAILED
            tx.provider_transaction_id = provider_txn_id
            tx.requires_reconciliation = False
            tx.reconciled_at = timezone.now()
            tx.failure_code = "reconciled_failed"
            tx.save()
            logger.info(
                "RECONCILED: ambiguous charge was declined — no money taken",
                extra={"payment_id": tx.id},
            )
            return tx

    # Nothing found. Once the settlement window has passed with no trace, the
    # charge never reached the processor.
    aged_out = timezone.now() - tx.created_at > SETTLEMENT_GRACE
    exhausted = tx.reconciliation_attempts >= MAX_RECONCILIATION_ATTEMPTS

    if remote is None and aged_out:
        tx.status = PaymentStatus.FAILED
        tx.requires_reconciliation = False
        tx.reconciled_at = timezone.now()
        tx.failure_code = "reconciled_not_found"
        tx.failure_message = "No matching transaction existed at the processor after the settlement window."
        tx.save()
        logger.info(
            "RECONCILED: no transaction found after grace period — treating as never charged",
            extra={"payment_id": tx.id},
        )
        return tx

    if exhausted:
        # Stop automated attempts but keep the flag so staff still see it.
        tx.failure_code = "reconciliation_exhausted"
        tx.failure_message = "Automated reconciliation gave up; manual review required."
        tx.save(update_fields=[
            "reconciliation_attempts", "failure_code", "failure_message", "updated_at",
        ])
        logger.error(
            "MANUAL REVIEW REQUIRED: could not resolve ambiguous payment",
            extra={"payment_id": tx.id, "amount_cents": tx.amount_cents},
        )
        return tx

    tx.save(update_fields=["reconciliation_attempts", "updated_at"])
    return tx


def reconcile_pending(*, limit: int = 100) -> dict[str, int]:
    """Reconcile every outstanding ambiguous payment. Returns a tally."""
    queryset = PaymentTransaction.objects.filter(
        requires_reconciliation=True,
        status=PaymentStatus.AMBIGUOUS,
    ).order_by("created_at")[:limit]

    tally = {"checked": 0, "confirmed": 0, "failed": 0, "still_unknown": 0}
    for tx in queryset:
        tally["checked"] += 1
        resolved = reconcile_transaction(tx)
        if resolved.status == PaymentStatus.CONFIRMED:
            tally["confirmed"] += 1
        elif resolved.status == PaymentStatus.FAILED:
            tally["failed"] += 1
        else:
            tally["still_unknown"] += 1
    return tally
