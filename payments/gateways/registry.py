from __future__ import annotations

from django.conf import settings

from payments.gateways.base import PaymentGateway
from payments.gateways.godaddy import GoDaddyPaymentGateway


def get_payment_gateway(provider: str | None = None) -> PaymentGateway:
    provider_slug = (provider or getattr(settings, "PAYMENTS_PROVIDER", "godaddy") or "godaddy").lower().strip()
    if provider_slug == GoDaddyPaymentGateway.slug:
        return GoDaddyPaymentGateway()
    raise ValueError(f"Unsupported payments provider: {provider_slug}")

