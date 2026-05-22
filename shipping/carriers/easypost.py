from __future__ import annotations

import os
from typing import Any

from django.conf import settings

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .base import (
    AddressInput,
    LabelRequest,
    LabelResult,
    RateQuote,
    RateRequest,
    ShippingCarrier,
    ValidationResult,
)


class EasyPostCarrier(ShippingCarrier):
    """
    EasyPost multi-carrier shipping.
    Wire: pip install easypost; set EASYPOST_API_KEY env var.
    Docs: https://www.easypost.com/docs/api
    """

    slug = "easypost"

    @property
    def _api_key(self) -> str:
        return (getattr(settings, "EASYPOST_API_KEY", "") or os.getenv("EASYPOST_API_KEY", "")).strip()

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        # Wire: import easypost; easypost.Address.create(...).verify()
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="EasyPost address validation requested (placeholder)",
            actor=actor,
            request=request,
            metadata={"provider": self.slug, "address_line_1": address.address_line_1},
        )
        return ValidationResult(
            provider=self.slug,
            is_valid=True,
            is_corrected=False,
            validated_address_line_1=address.address_line_1,
            validated_address_line_2=address.address_line_2,
            validated_city=address.city,
            validated_state=address.state,
            validated_postal_code=address.postal_code,
            validated_country=address.country,
            raw={"status": "not_implemented"},
        )

    def get_rates(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        # Wire: easypost.Shipment.create(...); parse .rates
        return [
            RateQuote(
                provider=self.slug,
                carrier="USPS",
                service_name="Priority",
                service_code="Priority",
                rate_cents=895,
                estimated_delivery_days=2,
                provider_rate_id="stub-easypost-rate-priority",
                raw={"status": "not_implemented"},
            ),
        ]

    def create_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        # Wire: easypost.Shipment.buy(rate={"id": label_request.provider_rate_id})
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message="EasyPost label creation requested (placeholder)",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "order_reference": label_request.order_reference,
            },
        )
        return LabelResult(
            provider=self.slug,
            carrier="USPS",
            service_name="Priority",
            tracking_number="9400111899223412345678",
            tracking_url="https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223412345678",
            label_format=label_request.label_format,
            label_url="",
            rate_cents=895,
            provider_label_id="stub-easypost-label-id",
            raw={"status": "not_implemented"},
        )

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        # Wire: easypost.Refund.create(shipment=provider_label_id)
        return {"status": "not_implemented", "provider_label_id": provider_label_id}
