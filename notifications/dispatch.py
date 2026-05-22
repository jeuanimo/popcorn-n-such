from __future__ import annotations

from django.utils import timezone

from notifications.models import NotificationChannel, NotificationStatus, OrderNotification
from notifications.registry import get_email_provider
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def send_tracking_email_for_order(*, order, label, actor=None, django_request=None) -> OrderNotification | None:
    recipient = getattr(order, "contact_email", "") or ""
    if not recipient:
        return None

    subject = f"Your order {order.order_number} has shipped!"
    body = (
        f"Your order {order.order_number} has shipped!\n"
        f"Carrier: {label.carrier}\n"
        f"Tracking: {label.tracking_number}\n"
    )
    if label.tracking_url:
        body += f"Track your package: {label.tracking_url}\n"

    provider = get_email_provider()
    result = provider.send(to_email=recipient, subject=subject, body=body)
    status = NotificationStatus.SENT if result.get("status") != "failed" else NotificationStatus.FAILED

    notification = OrderNotification.objects.create(
        order=order,
        channel=NotificationChannel.EMAIL,
        recipient=recipient,
        subject=subject,
        body=body,
        status=status,
        failure_reason="" if status == NotificationStatus.SENT else (result.get("error") or "send_failed"),
        sent_at=timezone.now() if status == NotificationStatus.SENT else None,
    )

    try:
        if getattr(order, "customer_id", None):
            from notifications.center import NotificationCenterService

            NotificationCenterService.notify_order_shipped(
                user=order.customer,
                order=order,
                tracking_number=label.tracking_number,
                tracking_url=label.tracking_url,
            )
    except Exception:
        pass

    log_audit_event(
        action=AuditAction.SECURITY_EVENT,
        message="Tracking email sent" if status == NotificationStatus.SENT else "Tracking email failed",
        actor=actor,
        request=django_request,
        metadata={
            "order_id": order.id,
            "notification_id": notification.id,
            "tracking_number": label.tracking_number,
            "provider": result.get("provider", "unknown"),
            "status": notification.status,
        },
    )
    return notification
