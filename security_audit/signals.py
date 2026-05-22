from django.contrib.admin.models import LogEntry
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AuditAction
from .utils import log_audit_event


@receiver(post_save, sender=LogEntry)
def mirror_admin_log_entry(sender, instance: LogEntry, created: bool, **kwargs):
    if not created:
        return

    log_audit_event(
        action=AuditAction.ADMIN_ACTION,
        message=f"Admin action: {instance.get_action_flag_display()} {instance.object_repr}",
        actor=instance.user,
        metadata={
            "content_type": str(instance.content_type),
            "object_id": instance.object_id,
            "change_message": instance.change_message,
        },
    )
