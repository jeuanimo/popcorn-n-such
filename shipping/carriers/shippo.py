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

_STUB_TRACKING = "9400111899223412345678"
_STUB_TRACKING_URL = (
    "https://tools.usps.com/go/TrackConfirmAction?tLabels=" + _STUB_TRACKING
)


class ShippoCarrier(ShippingCarrier):
    """
    Shippo multi-carrier shipping.
    Wire: pip install shippo; set SHIPPO_API_KEY env var.
    Docs: https://docs.goshippo.com/
    """

    slug = "shippo"

    @property
    def _api_key(self) -> str:
        return (getattr(settings, "SHIPPO_API_KEY", "") or os.getenv("SHIPPO_API_KEY", "")).strip()

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        # Wire: import shippo; shippo.Address.create(...).validate()
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Shippo address validation requested (placeholder)",
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
        # Wire: import shippo; shippo.Shipment.create(...); shippo.rate fetching
        return [
            RateQuote(
                provider=self.slug,
                carrier="USPS",
                service_name="Priority Mail",
                service_code="usps_priority",
                rate_cents=895,
                estimated_delivery_days=2,
                provider_rate_id="stub-shippo-rate-priority",
                raw={"status": "not_implemented"},
            ),
            RateQuote(
                provider=self.slug,
                carrier="USPS",
                service_name="First-Class Package",
                service_code="usps_first",
                rate_cents=495,
                estimated_delivery_days=5,
                provider_rate_id="stub-shippo-rate-first",
                raw={"status": "not_implemented"},
            ),
        ]

    def create_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        # Wire: import shippo; shippo.Transaction.create(rate=label_request.provider_rate_id, ...)
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message="Shippo label creation requested (placeholder)",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "order_reference": label_request.order_reference,
                "provider_rate_id": label_request.provider_rate_id,
            },
        )
        return LabelResult(
            provider=self.slug,
            carrier="USPS",
            service_name="Priority Mail",
            tracking_number=_STUB_TRACKING,
            tracking_url=_STUB_TRACKING_URL,
            label_format=label_request.label_format,
            label_url="",
            rate_cents=895,
            provider_label_id="stub-shippo-label-id",
            raw={"status": "not_implemented"},
        )

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        # Wire: import shippo; shippo.Transaction.invalidate(provider_label_id)
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message="Shippo label void requested (placeholder)",
            actor=actor,
            request=django_request,
            metadata={"provider": self.slug, "provider_label_id": provider_label_id},
        )
        return {"status": "not_implemented", "provider_label_id": provider_label_id}
