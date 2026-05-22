from __future__ import annotations

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from taxes.providers.base import TaxProvider, TaxQuoteRequest, TaxQuoteResult


class TaxJarProvider(TaxProvider):
    slug = "taxjar"

    def calculate_tax(self, request: TaxQuoteRequest, *, actor=None, django_request=None) -> TaxQuoteResult:
        # Placeholder implementation. Wire TaxJar API here.
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="TaxJar tax quote requested (placeholder)",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "order_id": request.order_id,
                "cart_id": request.cart_id,
            },
        )
        return TaxQuoteResult(provider=self.slug, status="not_implemented", tax_cents=0, raw={"status": "not_implemented"})

