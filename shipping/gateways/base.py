from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from shipping.carriers.base import AddressInput, LabelRequest, LabelResult, RateQuote, RateRequest, ValidationResult


class ShippingProvider(ABC):
    """
    Gateway-facing provider abstraction (carrier APIs).
    Carriers (shipping/carriers/*.py) can delegate to these providers.
    """

    slug: str

    @abstractmethod
    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    def get_shipping_options(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        raise NotImplementedError

    @abstractmethod
    def create_domestic_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        raise NotImplementedError

    @abstractmethod
    def create_return_label(self, original_provider_label_id: str, *, actor=None, django_request=None, label_format: str = "pdf_4x6") -> LabelResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def track_package(self, tracking_number: str, *, actor=None, django_request=None) -> dict[str, Any]:
        raise NotImplementedError

