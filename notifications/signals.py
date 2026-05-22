from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from notifications.alerts import NotificationService, _money
from notifications.models import StaffAlertEventType
from payments.signals import payment_confirmed, payment_failed
from shipping.models import AddressValidation, ShippingLabel
from teams.models import Team
from fundraisers.models import FundraiserParticipation, FundraiserRequest


@receiver(payment_confirmed)
def staff_alert_on_payment_confirmed(sender, order_id: int, payment_transaction_id: int, amount_cents: int, currency: str, **kwargs):
    from orders.models import Order

    order = Order.objects.filter(id=order_id).prefetch_related("items").first()
    if not order:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.NEW_PAID_ORDER,
        title=f"New paid order {order.order_number}",
        order=order,
        severity="info",
        payload={"order_id": order_id, "payment_transaction_id": payment_transaction_id},
        dedupe_key=f"paid_order:{order_id}",
    )

    threshold_cents = int(getattr(settings, "LARGE_ORDER_THRESHOLD_CENTS", 15000) or 15000)
    if int(order.total_cents) >= threshold_cents:
        NotificationService.emit_event(
            event_type=StaffAlertEventType.LARGE_ORDER_RECEIVED,
            title=f"Large order received {order.order_number}",
            message=f"Total {_money(order.total_cents)}",
            order=order,
            severity="warning",
            payload={"order_id": order_id},
            dedupe_key=f"large_order:{order_id}",
        )


@receiver(payment_failed)
def staff_alert_on_payment_failed(sender, order_id: int, payment_transaction_id: int, failure_code: str = "", **kwargs):
    from orders.models import Order

    order = Order.objects.filter(id=order_id).first()
    if not order:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.FAILED_PAYMENT,
        title=f"Failed payment for {order.order_number}",
        order=order,
        severity="warning",
        payload={"order_id": order_id, "payment_transaction_id": payment_transaction_id, "failure_code": failure_code},
        dedupe_key=f"failed_payment:{payment_transaction_id}",
    )


@receiver(post_save, sender=Team)
def staff_alert_team_created(sender, instance: Team, created: bool, **kwargs):
    if not created:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.NEW_TEAM_CREATED,
        title=f"New team created: {instance.name}",
        team=instance,
        severity="info",
        payload={"team_id": instance.id},
        dedupe_key=f"team_created:{instance.id}",
    )


@receiver(post_save, sender=ShippingLabel)
def staff_alert_label_created(sender, instance: ShippingLabel, created: bool, **kwargs):
    if not created:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.SHIPPING_LABEL_CREATED,
        title=f"Shipping label created for order #{instance.order_id}",
        order=instance.order,
        severity="info",
        payload={"label_id": instance.id, "tracking_number": instance.tracking_number},
        dedupe_key=f"label_created:{instance.id}",
    )


@receiver(post_save, sender=AddressValidation)
def staff_alert_address_validation_failed(sender, instance: AddressValidation, created: bool, **kwargs):
    if not created or instance.is_valid:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.ADDRESS_VALIDATION_FAILED,
        title=f"Address validation failed for order #{instance.order_id}",
        order=instance.order,
        severity="warning",
        payload={"address_validation_id": instance.id, "failure_reason": instance.failure_reason},
        dedupe_key=f"address_invalid:{instance.id}",
    )


@receiver(post_save, sender=FundraiserParticipation)
def staff_alert_fundraiser_signup(sender, instance: FundraiserParticipation, created: bool, **kwargs):
    if not created:
        return
    NotificationService.emit_event(
        event_type=StaffAlertEventType.NEW_FUNDRAISER_SIGNUP,
        title=f"New fundraiser signup: {instance.user.get_username()}",
        message=f"Invite: {instance.invite.campaign_name}",
        severity="info",
        payload={"participation_id": instance.id, "user_id": instance.user_id, "invite_id": instance.invite_id},
        dedupe_key=f"fundraiser_participation:{instance.id}",
    )


@receiver(post_save, sender=FundraiserRequest)
def staff_alert_fundraiser_request(sender, instance: FundraiserRequest, created: bool, **kwargs):
    if not created:
        return
    requester = instance.user.get_username() if instance.user_id else instance.contact_email
    NotificationService.emit_event(
        event_type=StaffAlertEventType.NEW_FUNDRAISER_SIGNUP,
        title=f"New fundraiser request: {instance.organization_name}",
        message=f"Requested by: {requester}",
        severity="info",
        payload={"fundraiser_request_id": instance.id, "user_id": instance.user_id},
        dedupe_key=f"fundraiser_request:{instance.id}",
    )
