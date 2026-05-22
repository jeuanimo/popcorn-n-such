from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from crm.models import CRMActivity, CRMContact, CRMNote, CRMTag, CRMTask
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def _audit(instance, *, message: str):
    try:
        log_audit_event(
            action=AuditAction.ADMIN_ACTION,
            message=message,
            actor=None,
            request=None,
            target=instance,
            metadata={"model": instance.__class__.__name__, "id": instance.pk},
        )
    except Exception:
        return


@receiver(post_save, sender=CRMContact)
def audit_contact_saved(sender, instance: CRMContact, created: bool, **kwargs):
    _audit(instance, message="CRM contact created" if created else "CRM contact updated")


@receiver(post_delete, sender=CRMContact)
def audit_contact_deleted(sender, instance: CRMContact, **kwargs):
    _audit(instance, message="CRM contact deleted")


@receiver(post_save, sender=CRMNote)
def audit_note_saved(sender, instance: CRMNote, created: bool, **kwargs):
    _audit(instance, message="CRM note created" if created else "CRM note updated")


@receiver(post_save, sender=CRMTask)
def audit_task_saved(sender, instance: CRMTask, created: bool, **kwargs):
    _audit(instance, message="CRM task created" if created else "CRM task updated")


@receiver(post_save, sender=CRMActivity)
def audit_activity_saved(sender, instance: CRMActivity, created: bool, **kwargs):
    _audit(instance, message="CRM activity created" if created else "CRM activity updated")


@receiver(post_save, sender=CRMTag)
def audit_tag_saved(sender, instance: CRMTag, created: bool, **kwargs):
    _audit(instance, message="CRM tag created" if created else "CRM tag updated")

