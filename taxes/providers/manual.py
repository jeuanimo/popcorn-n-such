from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from taxes.providers.base import ShippingAddress, TaxProvider, TaxQuoteRequest, TaxQuoteResult


class ManualTaxProvider(TaxProvider):
    slug = "manual"

    def _rate_for(self, *, address: ShippingAddress) -> Decimal:
        rates = getattr(settings, "MANUAL_TAX_RATES", {}) or {}
        state = (address.state or "").upper().strip()
        raw = rates.get(state, rates.get("*", "0.07"))
        try:
            return Decimal(str(raw))
        except Exception:
            return Decimal("0.07")

    def calculate_tax(self, request: TaxQuoteRequest, *, actor=None, django_request=None) -> TaxQuoteResult:
        rate = self._rate_for(address=request.destination)
        taxable_base = max(int(request.taxable_subtotal_cents), 0) + max(int(request.shipping_cents), 0)
        tax_cents = int(Decimal(taxable_base) * rate)

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Tax calculated (manual)",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "order_id": request.order_id,
                "cart_id": request.cart_id,
                "taxable_subtotal_cents": request.taxable_subtotal_cents,
                "shipping_cents": request.shipping_cents,
                "destination_state": request.destination.state,
                "tax_cents": tax_cents,
                "rate": str(rate),
            },
        )

        jurisdiction: dict[str, Any] = {
            "country": request.destination.country,
            "state": request.destination.state,
            "rate": str(rate),
        }
        return TaxQuoteResult(
            provider=self.slug,
            status="calculated",
            tax_cents=tax_cents,
            jurisdiction=jurisdiction,
            raw={"rate": str(rate)},
        )

