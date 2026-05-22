from dataclasses import dataclass

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


@dataclass
class FulfillmentRequest:
    order_reference: str
    warehouse_code: str


class FulfillmentService:
    def queue_for_packing(self, request: FulfillmentRequest, *, actor=None, django_request=None) -> dict:
        log_audit_event(
            action=AuditAction.ORDER_STATUS_CHANGE,
            message="Order queued for fulfillment",
            actor=actor,
            request=django_request,
            metadata={"order_reference": request.order_reference, "warehouse_code": request.warehouse_code},
        )
        return {"status": "queued", "order_reference": request.order_reference}
