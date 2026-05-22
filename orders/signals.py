from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .models import Order


@receiver(pre_save, sender=Order)
def log_order_status_changes(sender, instance: Order, **kwargs):
    if not instance.pk:
        return
    previous = Order.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    if previous and previous != instance.status:
        log_audit_event(
            action=AuditAction.ORDER_STATUS_CHANGE,
            message=f"Order status changed from {previous} to {instance.status}",
            # customer is None for guest orders; log_audit_event accepts nullable actors
            actor=instance.customer,
            target=instance,
            metadata={"previous_status": previous, "new_status": instance.status},
        )


@receiver(post_save, sender=Order)
def set_order_number(sender, instance: Order, created: bool, **kwargs):
    if created and not instance.order_number:
        number = f"PNS-{instance.created_at.strftime('%Y%m%d')}-{instance.pk:06d}"
        # Use queryset update to avoid re-triggering pre_save signal
        Order.objects.filter(pk=instance.pk).update(order_number=number)
        instance.order_number = number
