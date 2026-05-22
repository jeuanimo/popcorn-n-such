from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShippingAddress:
    address_line_1: str
    address_line_2: str
    city: str
    state: str
    postal_code: str
    country: str = "US"


@dataclass(frozen=True)
class TaxQuoteRequest:
    taxable_subtotal_cents: int
    shipping_cents: int
    destination: ShippingAddress
    currency: str = "USD"
    order_id: int | None = None
    cart_id: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TaxQuoteResult:
    provider: str
    status: str
    tax_cents: int
    jurisdiction: dict[str, Any] | None = None
    provider_reference_id: str | None = None
    raw: dict[str, Any] | None = None
    is_fallback: bool = False
    failure_code: str | None = None
    failure_message: str | None = None


class TaxProvider(ABC):
    slug: str

    def validate_address(self, *, address: ShippingAddress) -> tuple[bool, dict[str, Any]]:
        """
        Provider-specific address validation (optional).
        Return (is_valid, normalized_data).
        """
        return True, {"normalized": False}

    @abstractmethod
    def calculate_tax(self, request: TaxQuoteRequest, *, actor=None, django_request=None) -> TaxQuoteResult:
        raise NotImplementedError

