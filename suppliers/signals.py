from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from suppliers.models import (
    Supplier,
    SupplierDocument,
    SupplierNote,
    SupplierPerformanceNote,
    SupplierPurchaseOrder,
    SupplierTask,
)


def _audit(instance, *, message: str, action: str = AuditAction.ADMIN_ACTION):
    try:
        log_audit_event(
            action=action,
            message=message,
            actor=None,
            request=None,
            target=instance,
            metadata={"model": instance.__class__.__name__, "id": instance.pk},
        )
    except Exception:
        return


@receiver(post_save, sender=Supplier)
def audit_supplier_saved(sender, instance: Supplier, created: bool, **kwargs):
    _audit(instance, message="Supplier created" if created else "Supplier updated")


@receiver(post_delete, sender=Supplier)
def audit_supplier_deleted(sender, instance: Supplier, **kwargs):
    _audit(instance, message="Supplier deleted")


@receiver(post_save, sender=SupplierTask)
def audit_supplier_task_saved(sender, instance: SupplierTask, created: bool, **kwargs):
    _audit(instance, message="Supplier task created" if created else "Supplier task updated")


@receiver(post_save, sender=SupplierNote)
def audit_supplier_note_saved(sender, instance: SupplierNote, created: bool, **kwargs):
    _audit(instance, message="Supplier note created" if created else "Supplier note updated")


@receiver(post_save, sender=SupplierDocument)
def audit_supplier_document_saved(sender, instance: SupplierDocument, created: bool, **kwargs):
    _audit(instance, message="Supplier document uploaded" if created else "Supplier document updated")


@receiver(post_save, sender=SupplierPurchaseOrder)
def audit_supplier_po_saved(sender, instance: SupplierPurchaseOrder, created: bool, **kwargs):
    _audit(instance, message="Supplier purchase order created" if created else "Supplier purchase order updated")


@receiver(post_save, sender=SupplierPerformanceNote)
def audit_supplier_performance_saved(sender, instance: SupplierPerformanceNote, created: bool, **kwargs):
    _audit(instance, message="Supplier performance note created" if created else "Supplier performance note updated")

