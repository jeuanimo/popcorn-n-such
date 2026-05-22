from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction

from purchase_orders.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, ReceivingEvent
from purchase_orders.services import PurchaseOrderService


class PurchaseOrderItemInline(admin.TabularInline):
	model = PurchaseOrderItem
	extra = 0
	readonly_fields = ("line_total_cents", "created_at", "updated_at")


@admin.register(ReceivingEvent)
class ReceivingEventAdmin(admin.ModelAdmin):
	list_display = ("id", "purchase_order", "item", "received_delta", "override_used", "received_by", "received_at")
	list_filter = ("override_used", "received_at")
	search_fields = ("purchase_order__po_number",)
	readonly_fields = ("received_at",)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
	list_display = ("po_number", "supplier", "status", "order_date", "expected_delivery_date", "received_date", "total_cents", "created_at")
	list_filter = ("status", "supplier")
	search_fields = ("po_number", "supplier__name")
	readonly_fields = ("created_at", "updated_at", "subtotal_cents", "total_cents")
	inlines = [PurchaseOrderItemInline]
	actions = ["mark_submitted", "mark_ordered", "mark_canceled", "mark_paid"]

	def save_model(self, request, obj, form, change):
		# Keep totals consistent even when tax/shipping change.
		super().save_model(request, obj, form, change)
		PurchaseOrderService.recalc_purchase_order_totals(po=obj)

	@transaction.atomic
	def save_formset(self, request, form, formset, change):
		"""
		Handle receiving events and totals recalculation when inline items change.
		Prevents receiving more than ordered unless override is enabled.
		"""
		if formset.model is not PurchaseOrderItem:
			return super().save_formset(request, form, formset, change)

		instances = formset.save(commit=False)
		po: PurchaseOrder = form.instance

		for obj in instances:
			if obj.pk:
				old = PurchaseOrderItem.objects.select_for_update().get(pk=obj.pk)
				old_received = old.quantity_received
			else:
				old_received = 0

			desired_received = obj.quantity_received
			received_delta = desired_received - old_received
			if received_delta < 0:
				raise ValidationError("Decreasing quantity_received is not allowed; use an adjustment note instead.")

			# Save item edits without applying receiving deltas yet.
			obj.quantity_received = old_received
			obj.recalc_line_total()
			obj.save()

			if received_delta > 0:
				PurchaseOrderService.receive_item(
					item=obj,
					received_delta=received_delta,
					actor=request.user,
					request=request,
				)

		for deleted in formset.deleted_objects:
			deleted.delete()

		PurchaseOrderService.recalc_purchase_order_totals(po=po)

	@admin.action(description="Mark selected POs as Submitted")
	def mark_submitted(self, request, queryset):
		updated = queryset.update(status=PurchaseOrderStatus.SUBMITTED)
		self.message_user(request, f"Updated {updated} PO(s).")

	@admin.action(description="Mark selected POs as Ordered")
	def mark_ordered(self, request, queryset):
		updated = queryset.update(status=PurchaseOrderStatus.ORDERED)
		self.message_user(request, f"Updated {updated} PO(s).")

	@admin.action(description="Mark selected POs as Canceled")
	def mark_canceled(self, request, queryset):
		updated = queryset.update(status=PurchaseOrderStatus.CANCELED)
		self.message_user(request, f"Updated {updated} PO(s).")

	@admin.action(description="Mark selected POs as Paid")
	def mark_paid(self, request, queryset):
		updated = queryset.update(status=PurchaseOrderStatus.PAID)
		self.message_user(request, f"Updated {updated} PO(s).")


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
	list_display = ("id", "purchase_order", "supply", "sku", "description", "quantity_ordered", "quantity_received", "unit_cost_cents", "line_total_cents")
	list_filter = ("purchase_order__status",)
	search_fields = ("purchase_order__po_number", "supply__name", "sku__sku_code", "description")
	readonly_fields = ("created_at", "updated_at")
