from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from organizations.models import Organization, OrganizationDocument, OrganizationNote, OrganizationTask
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


@receiver(post_save, sender=Organization)
def audit_org_saved(sender, instance: Organization, created: bool, **kwargs):
    _audit(instance, message="Organization created" if created else "Organization updated")


@receiver(post_delete, sender=Organization)
def audit_org_deleted(sender, instance: Organization, **kwargs):
    _audit(instance, message="Organization deleted")


@receiver(post_save, sender=OrganizationTask)
def audit_org_task_saved(sender, instance: OrganizationTask, created: bool, **kwargs):
    _audit(instance, message="Organization task created" if created else "Organization task updated")


@receiver(post_save, sender=OrganizationNote)
def audit_org_note_saved(sender, instance: OrganizationNote, created: bool, **kwargs):
    _audit(instance, message="Organization note created" if created else "Organization note updated")


@receiver(post_save, sender=OrganizationDocument)
def audit_org_document_saved(sender, instance: OrganizationDocument, created: bool, **kwargs):
    _audit(instance, message="Organization document uploaded" if created else "Organization document updated")

