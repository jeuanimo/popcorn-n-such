from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("payments.tasks")


@shared_task(bind=True, max_retries=0)
def reconcile_ambiguous_payments(self, limit: int = 100) -> dict:
    """
    Resolve charges whose outcome was never received.

    Runs on a schedule rather than inline so a customer is never held waiting,
    and deliberately does not retry on failure: the next scheduled run picks up
    anything still outstanding, and the provider lookups are read-only.
    """
    from payments.reconciliation import reconcile_pending

    tally = reconcile_pending(limit=limit)
    if tally["checked"]:
        logger.info("Payment reconciliation run complete", extra=tally)
    if tally["confirmed"]:
        logger.error(
            "Reconciliation found charges that WERE taken but were not confirmed at checkout",
            extra=tally,
        )
    return tally
