from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_staff_event(self, event_id: int) -> None:
    """
    Deliver a NotificationEvent to all eligible staff members via email and/or SMS.

    Runs outside the request cycle so SMTP/Twilio latency never blocks checkout
    or webhook responses.  Retried up to 3 times on transient failures.
    """
    from notifications.alerts import NotificationService
    from notifications.models import NotificationEvent

    event = NotificationEvent.objects.filter(id=event_id).first()
    if event is None:
        logger.warning("deliver_staff_event: event %s not found — skipping", event_id)
        return
    try:
        NotificationService.deliver_event(event=event)
    except Exception as exc:
        logger.exception("deliver_staff_event failed for event %s", event_id)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def deliver_notification(self, notification_id: int, send_email: bool = True, send_sms: bool = False) -> None:
    """
    Deliver a customer Notification via the channels that were requested when it
    was created.  Re-reads preferences from the DB so stale in-memory state
    cannot cause over- or under-delivery.
    """
    from notifications.center import NotificationCenterService
    from notifications.models import Notification

    notif = Notification.objects.select_related("user").filter(id=notification_id).first()
    if notif is None:
        logger.warning("deliver_notification: notification %s not found — skipping", notification_id)
        return

    user = notif.user
    pref = NotificationCenterService.get_or_create_preferences(user)

    try:
        if send_email and pref.enabled and pref.receive_email:
            NotificationCenterService._deliver_email(
                notification=notif,
                user=user,
                title=notif.title,
                message=notif.message,
            )
        if send_sms and pref.enabled and NotificationCenterService._sms_allowed(user=user, pref=pref):
            NotificationCenterService._deliver_sms(
                notification=notif,
                user=user,
                title=notif.title,
                message=notif.message,
            )
    except Exception as exc:
        logger.exception("deliver_notification failed for notification %s", notification_id)
        raise self.retry(exc=exc)
