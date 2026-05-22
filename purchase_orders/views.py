from __future__ import annotations

from django.shortcuts import render
from django.views import View

from core.security import RoleRequiredMixin
from purchase_orders.services import PurchaseOrderService


class LowSupplyReorderSuggestionsView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")
	template_name = "purchase_orders/reorder_suggestions.html"

	def get(self, request):
		suggestions = PurchaseOrderService.low_supply_reorder_suggestions(limit=50)
		return render(request, self.template_name, {"suggestions": suggestions})
