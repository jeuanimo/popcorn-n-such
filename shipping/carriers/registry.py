from __future__ import annotations

from django.conf import settings

from .base import ShippingCarrier
from .easypost import EasyPostCarrier
from .pitney_bowes import PitneyBowesCarrier
from .shippo import ShippoCarrier
from .usps import USPSCarrier

_CARRIER_MAP: dict[str, type[ShippingCarrier]] = {
    ShippoCarrier.slug: ShippoCarrier,
    EasyPostCarrier.slug: EasyPostCarrier,
    USPSCarrier.slug: USPSCarrier,
    PitneyBowesCarrier.slug: PitneyBowesCarrier,
}


def get_shipping_carrier(provider: str | None = None) -> ShippingCarrier:
    slug = (provider or getattr(settings, "SHIPPING_PROVIDER", "shippo") or "shippo").lower().strip()
    cls = _CARRIER_MAP.get(slug)
    if cls is None:
        raise ValueError(f"Unsupported shipping provider: {slug!r}")
    return cls()
