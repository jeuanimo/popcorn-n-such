from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import UserProfile
from cart.models import Cart
from cart.services import CartService
from core.mail import send_runtime_mail
from notifications.services import TwilioSMSProvider
from orders.models import Order, OrderStatus
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .models import (
    AbandonedCartEvent,
    CartRecoveryMessage,
    CartRecoveryToken,
    EventCloseReason,
    MessageChannel,
    MessageStatus,
    RecoveryStage,
    TokenPurpose,
)

RECOVERY_SIGNING_SALT = "abandoned-cart-recovery"
UNSUBSCRIBE_SIGNING_SALT = "abandoned-cart-unsubscribe"


class AbandonedCartRecoveryService:
    STAGES = (
        (RecoveryStage.FIRST, 1),
        (RecoveryStage.SECOND, 24),
        (RecoveryStage.FINAL, 72),
    )

    COMPLETION_STATUSES = {
        OrderStatus.PLACED,
        OrderStatus.PAID,
        OrderStatus.FULFILLING,
        OrderStatus.SHIPPED,
    }

    @classmethod
    def abandonment_delay_minutes(cls) -> int:
        return int(getattr(settings, "ABANDONED_CART_ABANDONMENT_MINUTES", 60))

    @classmethod
    def event_expiry_hours(cls) -> int:
        return int(getattr(settings, "ABANDONED_CART_EVENT_EXPIRY_HOURS", 168))

    @classmethod
    def token_expiry_hours(cls) -> int:
        return int(getattr(settings, "ABANDONED_CART_TOKEN_EXPIRY_HOURS", 96))

    @classmethod
    def site_base_url(cls) -> str:
        base_url = getattr(settings, "SITE_BASE_URL", "http://localhost:8000")
        return base_url.rstrip("/")

    @classmethod
    def process_pending_events(cls, *, now=None, dry_run: bool = False) -> dict:
        now = now or timezone.now()
        counters = {
            "events_created": 0,
            "events_closed": 0,
            "email_sent": 0,
            "sms_sent": 0,
            "messages_failed": 0,
            "messages_skipped": 0,
            "recovered": 0,
        }
        processed_cart_ids = cls._process_open_events(now=now, dry_run=dry_run, counters=counters)
        cls._process_new_carts(now=now, dry_run=dry_run, counters=counters, skip_cart_ids=processed_cart_ids)
        return counters

    @classmethod
    def _process_open_events(cls, *, now, dry_run: bool, counters: dict) -> set:
        processed_cart_ids: set = set()
        open_events = AbandonedCartEvent.objects.filter(is_closed=False).select_related("cart", "cart__user")
        for event in open_events:
            processed_cart_ids.add(event.cart_id)
            cls._process_single_event(event=event, now=now, dry_run=dry_run, counters=counters)
        return processed_cart_ids

    @classmethod
    def _process_new_carts(cls, *, now, dry_run: bool, counters: dict, skip_cart_ids: set) -> None:
        carts = Cart.objects.filter(is_active=True).prefetch_related("items__sku", "attribution")
        for cart in carts:
            if cart.id in skip_cart_ids or not cart.items.exists():
                continue
            event, created = cls._get_or_create_event(cart=cart, now=now)
            if created:
                counters["events_created"] += 1
            cls._process_single_event(event=event, now=now, dry_run=dry_run, counters=counters)

    @classmethod
    def _process_single_event(cls, *, event: AbandonedCartEvent, now, dry_run: bool, counters: dict) -> None:
        cls._refresh_event_snapshot(event=event)

        changed, recovered = cls._maybe_close_or_recover(event=event, now=now)
        if recovered:
            counters["recovered"] += 1
        if changed:
            counters["events_closed"] += 1
            if not dry_run:
                event.save(update_fields=cls._event_update_fields())
            return

        if event.email_unsubscribed and (event.sms_opted_out or not event.sms_consent):
            event.close(reason=EventCloseReason.UNSUBSCRIBED, when=now)
            counters["events_closed"] += 1
            if not dry_run:
                event.save(update_fields=["is_closed", "close_reason", "closed_at", "updated_at"])
            return

        stage_to_send = cls._next_due_stage(event=event, now=now)
        if stage_to_send:
            results = cls._send_stage_reminders(event=event, stage=stage_to_send, now=now, dry_run=dry_run)
            counters["email_sent"] += results["email_sent"]
            counters["sms_sent"] += results["sms_sent"]
            counters["messages_failed"] += results["messages_failed"]
            counters["messages_skipped"] += results["messages_skipped"]
            if not dry_run:
                event.mark_stage_sent(stage_to_send, when=now)

        if not dry_run:
            event.save(update_fields=cls._event_update_fields())

    @classmethod
    def _event_update_fields(cls) -> list[str]:
        return [
            "customer_email",
            "customer_phone",
            "sms_consent",
            "fundraiser_campaign",
            "fundraiser_team",
            "fundraiser_seller",
            "last_activity_at",
            "abandoned_at",
            "expires_at",
            "first_reminder_sent_at",
            "second_reminder_sent_at",
            "final_reminder_sent_at",
            "recovered",
            "recovered_at",
            "recovered_order",
            "is_closed",
            "close_reason",
            "closed_at",
            "updated_at",
        ]

    @classmethod
    def _get_or_create_event(cls, *, cart: Cart, now):
        abandoned_at = cart.updated_at + timedelta(minutes=cls.abandonment_delay_minutes())
        defaults = {
            "last_activity_at": cart.updated_at,
            "abandoned_at": abandoned_at,
            "expires_at": abandoned_at + timedelta(hours=cls.event_expiry_hours()),
        }
        return AbandonedCartEvent.objects.get_or_create(cart=cart, defaults=defaults)

    @classmethod
    def _refresh_event_snapshot(cls, *, event: AbandonedCartEvent):
        cart = event.cart
        event.last_activity_at = cart.updated_at
        event.abandoned_at = cart.updated_at + timedelta(minutes=cls.abandonment_delay_minutes())
        event.expires_at = event.abandoned_at + timedelta(hours=cls.event_expiry_hours())

        event.customer_email = (cart.user.email if cart.user else "")[:254]
        phone = ""
        sms_consent = False
        if cart.user_id:
            phone = (cart.user.phone_number or "")[:25]
            profile = UserProfile.objects.filter(user=cart.user).first()
            sms_consent = bool(profile and profile.sms_opt_in)
            if profile:
                event.email_unsubscribed = event.email_unsubscribed or (not profile.marketing_opt_in)
                event.sms_opted_out = event.sms_opted_out or (not profile.sms_opt_in)
        event.customer_phone = phone
        event.sms_consent = sms_consent

        if hasattr(cart, "attribution"):
            event.fundraiser_campaign = cart.attribution.fundraiser_campaign[:120]
            event.fundraiser_team = cart.attribution.team[:120]
            event.fundraiser_seller = cart.attribution.seller[:120]

    @classmethod
    def _completed_order_for_event(cls, *, event: AbandonedCartEvent):
        user = event.cart.user
        if not user:
            return None

        return (
            Order.objects.filter(
                customer=user,
                status__in=cls.COMPLETION_STATUSES,
                created_at__gte=event.last_activity_at,
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def _maybe_close_or_recover(cls, *, event: AbandonedCartEvent, now):
        if event.is_closed:
            return False, False

        if not event.cart.is_active or not event.cart.items.exists():
            event.close(reason=EventCloseReason.EMPTIED, when=now)
            return True, False

        if now >= event.expires_at:
            event.close(reason=EventCloseReason.EXPIRED, when=now)
            return True, False

        completed_order = cls._completed_order_for_event(event=event)
        if completed_order:
            event.recovered = True
            event.recovered_at = now
            event.recovered_order = completed_order
            event.close(reason=EventCloseReason.RECOVERED, when=now)
            return True, True

        return False, False

    @classmethod
    def _next_due_stage(cls, *, event: AbandonedCartEvent, now):
        if now < event.abandoned_at:
            return None

        for stage, hours_after_abandonment in cls.STAGES:
            due_at = event.abandoned_at + timedelta(hours=hours_after_abandonment)
            sent_attr = f"{stage}_reminder_sent_at"
            if now >= due_at and getattr(event, sent_attr) is None:
                return stage
        return None

    @classmethod
    def _build_recovery_token(cls, *, event: AbandonedCartEvent, purpose: str, now=None) -> str:
        now = now or timezone.now()
        raw_token = secrets.token_urlsafe(32)
        CartRecoveryToken.objects.create(
            cart=event.cart,
            event=event,
            purpose=purpose,
            token_hash=CartRecoveryToken.hash_raw_token(raw_token),
            expires_at=now + timedelta(hours=cls.token_expiry_hours()),
        )

        payload = {"t": raw_token, "p": purpose}
        salt = RECOVERY_SIGNING_SALT if purpose == TokenPurpose.RECOVER else UNSUBSCRIBE_SIGNING_SALT
        return signing.dumps(payload, salt=salt)

    @classmethod
    def _build_links(cls, *, event: AbandonedCartEvent, dry_run: bool = False):
        if dry_run:
            recover_token = f"dry-run-recover-{event.pk}"
            unsubscribe_token = f"dry-run-unsubscribe-{event.pk}"
        else:
            recover_token = cls._build_recovery_token(event=event, purpose=TokenPurpose.RECOVER)
            unsubscribe_token = cls._build_recovery_token(event=event, purpose=TokenPurpose.UNSUBSCRIBE)
        recover_url = f"{cls.site_base_url()}/recovery/cart/{recover_token}/"
        unsubscribe_url = f"{cls.site_base_url()}/recovery/unsubscribe/{unsubscribe_token}/"
        preferences_url = f"{cls.site_base_url()}/accounts/preferences/"
        return recover_url, unsubscribe_url, preferences_url

    @classmethod
    def _render_email(cls, *, event: AbandonedCartEvent, recover_url: str, unsubscribe_url: str, preferences_url: str):
        subject = "You left something tasty in your cart"
        item_lines = []
        for item in event.cart.items.select_related("sku", "sku__product"):
            item_lines.append(f"- {item.sku.product.name} ({item.sku.size}) x{item.quantity}")

        body = "\n".join(
            [
                "You left something tasty in your Popcorn_N_Such cart:",
                *item_lines,
                "",
                f"Recover your cart securely: {recover_url}",
                "",
                f"Unsubscribe from cart reminders: {unsubscribe_url}",
                f"Manage notification preferences: {preferences_url}",
            ]
        )
        return subject, body

    @classmethod
    def _render_sms(cls, *, recover_url: str):
        return f"You still have popcorn waiting in your Popcorn_N_Such cart. Complete your order here: {recover_url}"

    @classmethod
    @transaction.atomic
    def _send_stage_reminders(cls, *, event: AbandonedCartEvent, stage: str, now, dry_run: bool):
        counters = {"email_sent": 0, "sms_sent": 0, "messages_failed": 0, "messages_skipped": 0}
        recover_url, unsubscribe_url, preferences_url = cls._build_links(event=event, dry_run=dry_run)

        if event.customer_email and not event.email_unsubscribed:
            subject, body = cls._render_email(
                event=event,
                recover_url=recover_url,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
            )
            email_result = cls._send_email_message(
                event=event,
                stage=stage,
                to_email=event.customer_email,
                subject=subject,
                body=body,
                now=now,
                dry_run=dry_run,
            )
            counters["email_sent"] += email_result["sent"]
            counters["messages_failed"] += email_result["failed"]
        else:
            cls._record_skipped_message(
                event=event,
                stage=stage,
                channel=MessageChannel.EMAIL,
                reason="Email missing or unsubscribed.",
                now=now,
                dry_run=dry_run,
            )
            counters["messages_skipped"] += 1

        if event.sms_consent and not event.sms_opted_out and event.customer_phone:
            sms_body = cls._render_sms(recover_url=recover_url)
            sms_result = cls._send_sms_message(
                event=event,
                stage=stage,
                to_phone=event.customer_phone,
                body=sms_body,
                now=now,
                dry_run=dry_run,
            )
            counters["sms_sent"] += sms_result["sent"]
            counters["messages_failed"] += sms_result["failed"]
        else:
            cls._record_skipped_message(
                event=event,
                stage=stage,
                channel=MessageChannel.SMS,
                reason="SMS consent not granted or phone unavailable.",
                now=now,
                dry_run=dry_run,
            )
            counters["messages_skipped"] += 1

        return counters

    @classmethod
    def _send_email_message(cls, *, event: AbandonedCartEvent, stage: str, to_email: str, subject: str, body: str, now, dry_run: bool) -> dict:
        if CartRecoveryMessage.objects.filter(event=event, stage=stage, channel=MessageChannel.EMAIL).exists():
            return {"sent": 0, "failed": 0}

        provider_response = {}
        status = MessageStatus.SENT
        failure_reason = ""

        if not dry_run:
            try:
                send_runtime_mail(
                    subject=subject,
                    message=body,
                    recipient_list=[to_email],
                    fail_silently=False,
                )
                provider_response = {"provider": "django_email"}
            except Exception as exc:  # noqa: BLE001
                status = MessageStatus.FAILED
                failure_reason = str(exc)[:250]
                provider_response = {"provider": "django_email", "error": failure_reason}

        CartRecoveryMessage.objects.create(
            event=event,
            stage=stage,
            channel=MessageChannel.EMAIL,
            status=status,
            to_value=to_email,
            subject=subject,
            body=body,
            provider_response=provider_response,
            failure_reason=failure_reason,
            sent_at=now if status == MessageStatus.SENT else None,
        )

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Abandoned cart email reminder {status}",
            actor=event.cart.user,
            target=event,
            metadata={"stage": stage, "channel": MessageChannel.EMAIL, "status": status},
        )

        if status == MessageStatus.SENT:
            return {"sent": 1, "failed": 0}
        return {"sent": 0, "failed": 1}

    @classmethod
    def _send_sms_message(cls, *, event: AbandonedCartEvent, stage: str, to_phone: str, body: str, now, dry_run: bool) -> dict:
        if CartRecoveryMessage.objects.filter(event=event, stage=stage, channel=MessageChannel.SMS).exists():
            return {"sent": 0, "failed": 0}

        provider_response = {}
        status = MessageStatus.SENT
        failure_reason = ""

        if not dry_run:
            try:
                provider_response = TwilioSMSProvider().send(to_phone=to_phone, message=body)
            except Exception as exc:  # noqa: BLE001
                status = MessageStatus.FAILED
                failure_reason = str(exc)[:250]
                provider_response = {"provider": "twilio", "error": failure_reason}

        CartRecoveryMessage.objects.create(
            event=event,
            stage=stage,
            channel=MessageChannel.SMS,
            status=status,
            to_value=to_phone,
            body=body,
            provider_response=provider_response,
            failure_reason=failure_reason,
            sent_at=now if status == MessageStatus.SENT else None,
        )

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message=f"Abandoned cart SMS reminder {status}",
            actor=event.cart.user,
            target=event,
            metadata={"stage": stage, "channel": MessageChannel.SMS, "status": status},
        )

        if status == MessageStatus.SENT:
            return {"sent": 1, "failed": 0}
        return {"sent": 0, "failed": 1}

    @classmethod
    def _record_skipped_message(cls, *, event: AbandonedCartEvent, stage: str, channel: str, reason: str, now, dry_run: bool):
        if dry_run:
            return

        if CartRecoveryMessage.objects.filter(event=event, stage=stage, channel=channel).exists():
            return

        CartRecoveryMessage.objects.create(
            event=event,
            stage=stage,
            channel=channel,
            status=MessageStatus.SKIPPED,
            to_value=event.customer_email if channel == MessageChannel.EMAIL else event.customer_phone,
            failure_reason=reason[:250],
            sent_at=None,
        )

    @classmethod
    def _decode_signed_token(cls, *, signed_token: str, purpose: str):
        salt = RECOVERY_SIGNING_SALT if purpose == TokenPurpose.RECOVER else UNSUBSCRIBE_SIGNING_SALT
        max_age = cls.token_expiry_hours() * 3600
        try:
            payload = signing.loads(signed_token, salt=salt, max_age=max_age)
        except signing.BadSignature as exc:
            raise ValidationError("Invalid or expired recovery link.") from exc

        raw_token = payload.get("t")
        payload_purpose = payload.get("p")
        if not raw_token or payload_purpose != purpose:
            raise ValidationError("Invalid recovery token payload.")
        return raw_token

    @classmethod
    def recover_from_signed_token(cls, *, request, signed_token: str):
        raw_token = cls._decode_signed_token(signed_token=signed_token, purpose=TokenPurpose.RECOVER)
        token_hash = CartRecoveryToken.hash_raw_token(raw_token)

        token = (
            CartRecoveryToken.objects.select_related("cart", "event")
            .filter(token_hash=token_hash, purpose=TokenPurpose.RECOVER)
            .first()
        )
        if not token or not token.is_usable:
            raise ValidationError("Recovery token is invalid or has expired.")

        cart = token.cart
        if not cart.items.exists() or not cart.is_active:
            raise ValidationError("Cart is no longer recoverable.")

        CartService.get_or_create_cart(request)
        if request.user.is_authenticated:
            cart.user = request.user
            cart.session_key = request.session.session_key
            cart.save(update_fields=["user", "session_key", "updated_at"])
        else:
            cart.user = None
            cart.session_key = request.session.session_key
            cart.save(update_fields=["user", "session_key", "updated_at"])

        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Abandoned cart recovered from signed link",
            actor=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
            request=request,
            target=cart,
        )
        return cart

    @classmethod
    def unsubscribe_from_signed_token(cls, *, signed_token: str):
        raw_token = cls._decode_signed_token(signed_token=signed_token, purpose=TokenPurpose.UNSUBSCRIBE)
        token_hash = CartRecoveryToken.hash_raw_token(raw_token)

        token = (
            CartRecoveryToken.objects.select_related("event")
            .filter(token_hash=token_hash, purpose=TokenPurpose.UNSUBSCRIBE)
            .first()
        )
        if not token or not token.is_usable:
            raise ValidationError("Unsubscribe token is invalid or has expired.")

        event = token.event
        event.email_unsubscribed = True
        event.sms_opted_out = True
        event.save(update_fields=["email_unsubscribed", "sms_opted_out", "updated_at"])

        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Abandoned cart reminders unsubscribed via signed link",
            actor=event.cart.user,
            target=event,
        )
        return event
