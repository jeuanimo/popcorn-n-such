from __future__ import annotations

from typing import Any

from shipping.gateways.usps import USPSProvider, USPSProviderError

from .base import (
    AddressInput,
    LabelRequest,
    LabelResult,
    RateQuote,
    RateRequest,
    ShippingCarrier,
    ValidationResult,
)


class USPSCarrier(ShippingCarrier):
    """
    USPS direct integration (modern API scaffold).
    Credentials: USPS_CLIENT_ID / USPS_CLIENT_SECRET + USPS_ENV.
    """

    slug = "usps"

    def __init__(self):
        self.provider = USPSProvider()

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        try:
            return self.provider.validate_address(address, actor=actor, request=request)
        except USPSProviderError as exc:
            return ValidationResult(provider=self.slug, is_valid=False, is_corrected=False, failure_reason=str(exc), raw={})

    def get_rates(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        try:
            return self.provider.get_shipping_options(rate_request, actor=actor, django_request=django_request)
        except USPSProviderError:
            # Fallback: return no options, letting callers use Shippo/EasyPost if configured.
            return []

    def create_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        return self.provider.create_domestic_label(label_request, actor=actor, django_request=django_request)

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        try:
            return self.provider.cancel_label(provider_label_id, actor=actor, django_request=django_request)
        except USPSProviderError as exc:
            return {"status": "error", "error": str(exc), "provider_label_id": provider_label_id}
