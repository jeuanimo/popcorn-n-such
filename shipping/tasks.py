from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_tracking_email(self, order_id: int, label_id: int) -> None:
    """
    Email the customer their tracking number after a shipping label is created.

    Dispatched by LabelCreateView immediately after the label is persisted so
    the staff label-generation response is not blocked by SMTP latency.
    """
    from notifications.dispatch import send_tracking_email_for_order
    from orders.models import Order
    from shipping.models import ShippingLabel

    order = Order.objects.filter(id=order_id).first()
    label = ShippingLabel.objects.filter(id=label_id).first()

    if order is None or label is None:
        logger.warning(
            "send_tracking_email: order %s or label %s not found — skipping",
            order_id,
            label_id,
        )
        return

    # Draft labels have no tracking number; nothing useful to email.
    if label.provider == "draft":
        return

    try:
        send_tracking_email_for_order(order=order, label=label)
    except Exception as exc:
        logger.exception(
            "send_tracking_email failed for order %s / label %s", order_id, label_id
        )
        raise self.retry(exc=exc)
