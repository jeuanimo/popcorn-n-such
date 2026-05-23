from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import logging

logger = logging.getLogger(__name__)

from notifications.models import (
    NotificationDeliveryChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationEvent,
    StaffAlertEventType,
    StaffAlertPreference,
)
from notifications.registry import get_sms_provider
from core.mail import send_runtime_mail
from core.runtime_settings import get_runtime_setting
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def _money(cents: int) -> str:
    return f"${Decimal(int(cents)) / 100:.2f}"


def _safe_city_state(order) -> str:
    city = (getattr(order, "shipping_city", "") or "").strip()
    state = (getattr(order, "shipping_state", "") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or "N/A"


def _staff_queryset():
    from accounts.models import User

    return User.objects.filter(is_staff=True, is_active=True)


@dataclass(frozen=True)
class DeliveryDecision:
    email: bool
    sms: bool
    internal: bool


class NotificationService:
    """
    Staff alert delivery:
    - Email uses Django email backend (`send_mail`).
    - SMS uses pluggable provider (Twilio placeholder).
    - Internal notifications are represented as `NotificationDeliveryLog(channel=internal)`.
    """

    @staticmethod
    def get_or_create_preference(user) -> StaffAlertPreference:
        pref, _ = StaffAlertPreference.objects.get_or_create(user=user)
        return pref

    @staticmethod
    def _decide(pref: StaffAlertPreference, *, event_type: str) -> DeliveryDecision:
        if not pref.is_event_enabled(event_type):
            return DeliveryDecision(email=False, sms=False, internal=False)
        return DeliveryDecision(
            email=bool(pref.receive_email),
            sms=bool(pref.receive_sms and pref.sms_opt_in and (pref.user.phone_number or "").strip()),
            internal=bool(pref.receive_internal),
        )

    @classmethod
    @transaction.atomic
    def emit_event(
        cls,
        *,
        event_type: str,
        title: str,
        message: str = "",
        severity: str = "info",
        order=None,
        team=None,
        sku=None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str = "",
        actor=None,
        request=None,
    ) -> NotificationEvent:
        if dedupe_key:
            existing = NotificationEvent.objects.filter(dedupe_key=dedupe_key).order_by("-created_at").first()
            if existing and (timezone.now() - existing.created_at).total_seconds() < 60:
                return existing

        event = NotificationEvent.objects.create(
            event_type=event_type,
            title=title,
            message=message,
            severity=severity,
            order=order,
            team=team,
            sku=sku,
            payload=payload or {},
            dedupe_key=dedupe_key,
        )

        from notifications.tasks import deliver_staff_event
        transaction.on_commit(lambda: deliver_staff_event.delay(event.id))
        return event

    @classmethod
    def deliver_event(cls, *, event: NotificationEvent, actor=None, request=None) -> None:
        sms_provider = get_sms_provider()

        for user in _staff_queryset():
            pref = cls.get_or_create_preference(user)
            decision = cls._decide(pref, event_type=event.event_type)
            if not (decision.email or decision.sms or decision.internal):
                NotificationDeliveryLog.objects.create(
                    event=event,
                    user=user,
                    channel=NotificationDeliveryChannel.INTERNAL,
                    status=NotificationDeliveryStatus.SKIPPED,
                    failure_reason="disabled_by_preference",
                )
                continue

            if decision.internal:
                NotificationDeliveryLog.objects.create(
                    event=event,
                    user=user,
                    channel=NotificationDeliveryChannel.INTERNAL,
                    status=NotificationDeliveryStatus.SENT,
                    recipient=user.get_username(),
                )

            if decision.email and (user.email or "").strip():
                subject = f"[Popcorn_N_Such] {event.title}"
                body = cls._render_email(event=event)
                try:
                    send_runtime_mail(subject=subject, message=body, recipient_list=[user.email], fail_silently=False)
                    NotificationDeliveryLog.objects.create(
                        event=event,
                        user=user,
                        channel=NotificationDeliveryChannel.EMAIL,
                        status=NotificationDeliveryStatus.SENT,
                        recipient=user.email,
                        subject=subject,
                        body=body,
                        sent_at=timezone.now(),
                    )
                except Exception as exc:  # noqa: BLE001
                    NotificationDeliveryLog.objects.create(
                        event=event,
                        user=user,
                        channel=NotificationDeliveryChannel.EMAIL,
                        status=NotificationDeliveryStatus.FAILED,
                        recipient=user.email,
                        subject=subject,
                        body=body,
                        failure_reason=str(exc)[:255],
                    )

            if decision.sms:
                phone = (user.phone_number or "").strip()
                sms_body = cls._render_sms(event=event)
                try:
                    result = sms_provider.send(to_phone=phone, message=sms_body)
                    status = NotificationDeliveryStatus.SENT if result.get("status") != "failed" else NotificationDeliveryStatus.FAILED
                    NotificationDeliveryLog.objects.create(
                        event=event,
                        user=user,
                        channel=NotificationDeliveryChannel.SMS,
                        status=status,
                        recipient=phone,
                        body=sms_body,
                        sent_at=timezone.now() if status == NotificationDeliveryStatus.SENT else None,
                        failure_reason="" if status == NotificationDeliveryStatus.SENT else (result.get("error") or "send_failed"),
                    )
                except Exception as exc:  # noqa: BLE001
                    NotificationDeliveryLog.objects.create(
                        event=event,
                        user=user,
                        channel=NotificationDeliveryChannel.SMS,
                        status=NotificationDeliveryStatus.FAILED,
                        recipient=phone,
                        body=sms_body,
                        failure_reason=str(exc)[:255],
                    )

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Staff notification event delivered",
            actor=actor,
            request=request,
            metadata={"event_id": event.id, "event_type": event.event_type},
        )

    @staticmethod
    def _render_email(*, event: NotificationEvent) -> str:
        if event.event_type == StaffAlertEventType.NEW_PAID_ORDER and event.order_id:
            order = event.order
            lines = [
                f"New paid order: {order.order_number}",
                f"Total: {_money(order.total_cents)}",
                f"Items: {order.items.count()}",
                f"Ship to: {_safe_city_state(order)}",
                "",
                "Order items:",
            ]
            for item in order.items.all()[:50]:
                lines.append(f"- {item.quantity} x {item.product_name_snapshot} ({item.sku.sku_code})")
            return "\n".join(lines)
        return event.message or event.title

    @staticmethod
    def _render_sms(*, event: NotificationEvent) -> str:
        # Keep SMS short and avoid sensitive payment details.
        if event.event_type == StaffAlertEventType.NEW_PAID_ORDER and event.order_id:
            o = event.order
            return f"New Popcorn_N_Such order {o.order_number} paid: {_money(o.total_cents)}, {o.items.count()} items. Ship to {_safe_city_state(o)}."
        if event.event_type == StaffAlertEventType.FAILED_PAYMENT and event.order_id:
            o = event.order
            return f"Payment failed for order {o.order_number}. Total {_money(o.total_cents)}. Check admin."
        return (event.title or "Popcorn_N_Such alert")[:140]
