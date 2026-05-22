from __future__ import annotations

from typing import Any

from shipping.gateways.pitney_bowes import PitneyBowesProvider, PitneyBowesProviderError

from .base import (
    AddressInput,
    LabelRequest,
    LabelResult,
    RateQuote,
    RateRequest,
    ShippingCarrier,
    ValidationResult,
)


class PitneyBowesCarrier(ShippingCarrier):
    """
    Pitney Bowes Shipping APIs.
    Wire: register at https://developer.pitneybowes.com/; set PITNEY_BOWES_API_KEY env var.
    Docs: https://developer.pitneybowes.com/en/shipping.html
    """

    slug = "pitney_bowes"

    def __init__(self):
        self.provider = PitneyBowesProvider()

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        try:
            return self.provider.validate_address(address, actor=actor, request=request)
        except PitneyBowesProviderError as exc:
            return ValidationResult(provider=self.slug, is_valid=False, is_corrected=False, failure_reason=str(exc), raw={})

    def get_rates(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        try:
            return self.provider.get_rates(rate_request, actor=actor, django_request=django_request)
        except PitneyBowesProviderError:
            return []

    def create_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        return self.provider.create_label(label_request, actor=actor, django_request=django_request)

    def create_label_v2(
        self,
        label_request: LabelRequest,
        *,
        carrier_key: str = "usps_ground",
        actor=None,
        django_request=None,
    ) -> LabelResult:
        return self.provider.create_label_v2(
            label_request,
            carrier_key=carrier_key,
            actor=actor,
            django_request=django_request,
        )

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        try:
            return self.provider.void_label(provider_label_id, actor=actor, django_request=django_request)
        except PitneyBowesProviderError as exc:
            return {"status": "error", "error": str(exc), "provider_label_id": provider_label_id}
