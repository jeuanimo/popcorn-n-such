from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AddressInput:
    recipient_name: str
    address_line_1: str
    city: str
    state: str
    postal_code: str
    country: str = "US"
    address_line_2: str = ""
    phone: str = ""


@dataclass(frozen=True)
class PackageInput:
    weight_oz: float
    length_in: float = 0.0
    width_in: float = 0.0
    height_in: float = 0.0


@dataclass(frozen=True)
class RateRequest:
    from_postal_code: str
    from_country: str
    to_address: AddressInput
    package: PackageInput
    order_reference: str = ""


@dataclass(frozen=True)
class LabelRequest:
    provider_rate_id: str
    from_address: AddressInput
    to_address: AddressInput
    package: PackageInput
    order_reference: str
    label_format: str = "pdf_4x6"


@dataclass(frozen=True)
class ValidationResult:
    provider: str
    is_valid: bool
    is_corrected: bool
    validated_address_line_1: str = ""
    validated_address_line_2: str = ""
    validated_city: str = ""
    validated_state: str = ""
    validated_postal_code: str = ""
    validated_country: str = ""
    failure_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RateQuote:
    provider: str
    carrier: str
    service_name: str
    service_code: str
    rate_cents: int
    currency: str = "USD"
    estimated_delivery_days: int | None = None
    provider_rate_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LabelResult:
    provider: str
    carrier: str
    service_name: str
    tracking_number: str
    tracking_url: str
    label_format: str
    label_url: str
    rate_cents: int = 0
    currency: str = "USD"
    provider_label_id: str = ""
    label_zpl: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    failure_code: str = ""
    failure_message: str = ""


class ShippingCarrier(ABC):
    slug: str

    @abstractmethod
    def validate_address(
        self,
        address: AddressInput,
        *,
        actor=None,
        request=None,
    ) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    def get_rates(
        self,
        rate_request: RateRequest,
        *,
        actor=None,
        django_request=None,
    ) -> list[RateQuote]:
        raise NotImplementedError

    @abstractmethod
    def create_label(
        self,
        label_request: LabelRequest,
        *,
        actor=None,
        django_request=None,
    ) -> LabelResult:
        raise NotImplementedError

    @abstractmethod
    def void_label(
        self,
        provider_label_id: str,
        *,
        actor=None,
        django_request=None,
    ) -> dict[str, Any]:
        raise NotImplementedError
