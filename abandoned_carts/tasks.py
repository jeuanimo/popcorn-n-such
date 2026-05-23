from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def process_abandoned_carts() -> dict:
    """
    Periodic task (default: every 30 minutes via Celery Beat) that scans all
    active carts, creates AbandonedCartEvent records where needed, and sends
    the appropriate recovery email/SMS for each reminder stage.

    The management command `process_abandoned_carts` still works for manual
    runs; this task uses the same service method so behaviour is identical.
    """
    from abandoned_carts.services import AbandonedCartRecoveryService

    counters = AbandonedCartRecoveryService.process_pending_events()
    logger.info(
        "Abandoned cart scan complete: created=%s closed=%s email=%s sms=%s "
        "failed=%s skipped=%s recovered=%s",
        counters.get("events_created", 0),
        counters.get("events_closed", 0),
        counters.get("email_sent", 0),
        counters.get("sms_sent", 0),
        counters.get("messages_failed", 0),
        counters.get("messages_skipped", 0),
        counters.get("recovered", 0),
    )
    return counters
