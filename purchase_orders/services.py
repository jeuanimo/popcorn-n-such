from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from products.models import SKU
from purchase_orders.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, ReceivingEvent
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from supplies.models import Supply


def _is_staff(actor) -> bool:
	return bool(actor and (getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False)))


@dataclass(frozen=True)
class ReorderSuggestion:
	supply: Supply
	current_qty: Decimal
	threshold: Decimal
	suggested_qty: Decimal


class PurchaseOrderService:
	@staticmethod
	@transaction.atomic
	def recalc_purchase_order_totals(*, po: PurchaseOrder) -> PurchaseOrder:
		for item in po.items.select_for_update().all():
			item.recalc_line_total()
			item.save(update_fields=["line_total_cents", "updated_at"])
		po.recalc_totals()
		po.save(update_fields=["subtotal_cents", "total_cents", "updated_at"])
		return po

	@staticmethod
	def _validate_receive_delta(*, item: PurchaseOrderItem, delta: Decimal, allow_override: bool) -> bool:
		if delta <= 0:
			raise ValidationError("Received quantity must be greater than zero.")
		new_total = Decimal(item.quantity_received) + Decimal(delta)
		override_used = False
		if new_total > Decimal(item.quantity_ordered):
			override_used = True
			if not allow_override:
				raise ValidationError("Cannot receive more than ordered (override disabled).")
		return override_used

	@classmethod
	@transaction.atomic
	def receive_item(
		cls,
		*,
		item: PurchaseOrderItem,
		received_delta: Decimal,
		actor,
		request=None,
		allow_override: bool | None = None,
		notes: str = "",
	) -> PurchaseOrderItem:
		if not _is_staff(actor):
			raise PermissionDenied("Staff/admin only.")

		allow_override_flag = bool(
			allow_override if allow_override is not None else getattr(settings, "PURCHASE_ORDER_ALLOW_OVER_RECEIVE", False)
		)
		override_used = cls._validate_receive_delta(item=item, delta=received_delta, allow_override=allow_override_flag)

		po = PurchaseOrder.objects.select_for_update().get(id=item.purchase_order_id)
		item = PurchaseOrderItem.objects.select_for_update().get(id=item.id)

		item.quantity_received = Decimal(item.quantity_received) + Decimal(received_delta)
		item.save(update_fields=["quantity_received", "updated_at"])

		# Update inventories
		if item.supply_id:
			supply = Supply.objects.select_for_update().get(id=item.supply_id)
			supply.inventory_quantity = Decimal(supply.inventory_quantity) + Decimal(received_delta)
			supply.save(update_fields=["inventory_quantity", "updated_at"])
		if item.sku_id:
			sku = SKU.objects.select_for_update().get(id=item.sku_id)
			if Decimal(received_delta) != Decimal(int(received_delta)):
				raise ValidationError("SKU receiving quantity must be a whole number.")
			sku.inventory_quantity = int(sku.inventory_quantity) + int(received_delta)
			sku.save(update_fields=["inventory_quantity", "updated_at"])

		ReceivingEvent.objects.create(
			purchase_order=po,
			item=item,
			received_delta=received_delta,
			override_used=override_used,
			notes=notes[:255],
			received_by=actor,
		)

		log_audit_event(
			action=AuditAction.ADMIN_ACTION,
			message="Purchase order item received",
			actor=actor,
			request=request,
			target=po,
			metadata={
				"po_number": po.po_number,
				"item_id": item.id,
				"received_delta": str(received_delta),
				"override_used": override_used,
			},
		)

		cls._update_po_receive_status(po=po)
		return item

	@staticmethod
	def _update_po_receive_status(*, po: PurchaseOrder) -> None:
		items = list(po.items.all())
		if not items:
			return
		any_received = any(Decimal(i.quantity_received) > 0 for i in items)
		all_received = all(Decimal(i.quantity_received) >= Decimal(i.quantity_ordered) and Decimal(i.quantity_ordered) > 0 for i in items)

		if all_received:
			po.status = PurchaseOrderStatus.RECEIVED
			po.received_date = timezone.localdate()
			po.save(update_fields=["status", "received_date", "updated_at"])
		elif any_received:
			po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
			po.save(update_fields=["status", "updated_at"])

	@staticmethod
	def low_supply_reorder_suggestions(*, limit: int = 25) -> list[ReorderSuggestion]:
		low_supplies = Supply.objects.filter(is_active=True).order_by("name")
		out: list[ReorderSuggestion] = []
		for supply in low_supplies:
			if not supply.is_low_stock:
				continue
			current_qty = Decimal(supply.inventory_quantity)
			threshold = Decimal(supply.low_stock_threshold)
			# Suggested reorder: bring to 2x threshold (simple heuristic)
			target = threshold * Decimal("2")
			suggested = max(Decimal("0"), target - current_qty)
			out.append(ReorderSuggestion(supply=supply, current_qty=current_qty, threshold=threshold, suggested_qty=suggested))
			if len(out) >= limit:
				break
		return out

