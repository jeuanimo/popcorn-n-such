from __future__ import annotations

from django.utils import timezone

from notifications.models import (
    Notification,
    NotificationDeliveryChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationPreference,
    NotificationType,
)
from notifications.registry import get_email_provider, get_sms_provider


class NotificationCenterService:

    @staticmethod
    def get_or_create_preferences(user) -> NotificationPreference:
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        return pref

    @staticmethod
    def _sms_allowed(*, user, pref: NotificationPreference) -> bool:
        if not pref.receive_sms or not pref.sms_opt_in:
            return False
        phone = (getattr(user, "phone_number", "") or "").strip()
        if not phone:
            return False
        profile = getattr(user, "profile", None)
        if profile is not None and getattr(profile, "sms_opt_in", False) is not True:
            return False
        return True

    # ------------------------------------------------------------------
    # Delivery helpers — each owns one channel, reducing notify() nesting
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_status(result: dict) -> str:
        return (
            NotificationDeliveryStatus.SENT
            if result.get("status") != "failed"
            else NotificationDeliveryStatus.FAILED
        )

    @classmethod
    def _log_internal(cls, *, notification: Notification, user) -> None:
        NotificationDeliveryLog.objects.create(
            notification=notification,
            user=user,
            channel=NotificationDeliveryChannel.INTERNAL,
            status=NotificationDeliveryStatus.SENT,
        )

    @classmethod
    def _deliver_email(cls, *, notification: Notification, user, title: str, message: str) -> None:
        to_email = (getattr(user, "email", "") or "").strip()
        if not to_email:
            return
        result = get_email_provider().send(to_email=to_email, subject=title, body=message or title)
        status = cls._provider_status(result)
        NotificationDeliveryLog.objects.create(
            notification=notification,
            user=user,
            channel=NotificationDeliveryChannel.EMAIL,
            status=status,
            recipient=to_email,
            subject=title,
            body=message or title,
            failure_reason="" if status == NotificationDeliveryStatus.SENT else (result.get("error") or "send_failed"),
            sent_at=timezone.now() if status == NotificationDeliveryStatus.SENT else None,
        )

    @classmethod
    def _deliver_sms(cls, *, notification: Notification, user, title: str, message: str) -> None:
        phone = (getattr(user, "phone_number", "") or "").strip()
        body = (title or message)[:140]
        result = get_sms_provider().send(to_phone=phone, message=body)
        status = cls._provider_status(result)
        NotificationDeliveryLog.objects.create(
            notification=notification,
            user=user,
            channel=NotificationDeliveryChannel.SMS,
            status=status,
            recipient=phone,
            body=body,
            failure_reason="" if status == NotificationDeliveryStatus.SENT else (result.get("error") or "send_failed"),
            sent_at=timezone.now() if status == NotificationDeliveryStatus.SENT else None,
        )

    # ------------------------------------------------------------------
    # Core notify
    # ------------------------------------------------------------------

    @classmethod
    def notify(
        cls,
        *,
        user,
        notification_type: str,
        title: str,
        message: str = "",
        payload: dict | None = None,
        order=None,
        send_email: bool = True,
        send_sms: bool = False,
    ) -> Notification:
        """
        Creates an in-app notification and optionally dispatches email/SMS.
        Do not include sensitive payment details in message/payload.
        """
        payload = payload or {}
        pref = cls.get_or_create_preferences(user)

        if not pref.is_type_enabled(notification_type):
            return Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                payload=payload,
                order=order,
                read_at=timezone.now(),  # silently hidden per preference
            )

        notification = Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            payload=payload,
            order=order,
        )

        if pref.enabled and pref.receive_in_app:
            cls._log_internal(notification=notification, user=user)

        if send_email and pref.enabled and pref.receive_email:
            cls._deliver_email(notification=notification, user=user, title=title, message=message)

        if send_sms and pref.enabled and cls._sms_allowed(user=user, pref=pref):
            cls._deliver_sms(notification=notification, user=user, title=title, message=message)

        return notification

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @classmethod
    def notify_new_order(cls, *, user, order) -> None:
        cls.notify(
            user=user,
            notification_type=NotificationType.NEW_ORDER,
            title=f"Order received: {order.order_number or order.pk}",
            message=f"Thanks! Your order total is ${order.total_cents / 100:.2f}.",
            payload={"order_id": order.id, "order_number": order.order_number},
            order=order,
            send_email=False,
            send_sms=False,
        )

    @classmethod
    def notify_label_printed(cls, *, user, label, is_reprint: bool = False) -> None:
        action = "reprinted" if is_reprint else "printed"
        order_ref = ""
        if label.order_id:
            order_number = getattr(label.order, "order_number", None) or label.order_id
            order_ref = f" for order {order_number}"
        cls.notify(
            user=user,
            notification_type=NotificationType.LABEL_CREATED,
            title=f"Label {action}: {label.tracking_number}",
            message=(
                f"{label.carrier} / {label.service_name} label{order_ref} was {action}. "
                "If the print failed, use the Reprint button in the Label Monitor."
            ),
            payload={
                "label_id": label.id,
                "tracking_number": label.tracking_number,
                "print_count": label.print_count,
                "is_reprint": is_reprint,
            },
            send_email=False,
            send_sms=False,
        )

    @classmethod
    def notify_order_shipped(cls, *, user, order, tracking_number: str = "", tracking_url: str = "") -> None:
        msg = f"Your order {order.order_number} has shipped."
        if tracking_number:
            msg += f" Tracking: {tracking_number}."
        cls.notify(
            user=user,
            notification_type=NotificationType.ORDER_SHIPPED,
            title=f"Order shipped: {order.order_number or order.pk}",
            message=msg,
            payload={"order_id": order.id, "tracking_number": tracking_number, "tracking_url": tracking_url},
            order=order,
            send_email=False,
            send_sms=False,
        )
