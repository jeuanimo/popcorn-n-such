from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def run_post_order_tasks(self, order_id: int) -> None:
    """
    Run fulfillment queuing and customer/staff notifications after an order is
    confirmed.  Executes outside the checkout request so the customer is not
    held waiting for SMTP or fulfillment API calls.
    """
    from orders.models import Order
    from orders.services import CheckoutService

    order = Order.objects.filter(id=order_id).first()
    if order is None:
        logger.warning("run_post_order_tasks: order %s not found — skipping", order_id)
        return
    try:
        CheckoutService().post_order_tasks(order)
    except Exception as exc:
        logger.exception("run_post_order_tasks failed for order %s", order_id)
        raise self.retry(exc=exc)
