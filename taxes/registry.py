from __future__ import annotations

from django.conf import settings

from taxes.providers.avalara import AvalaraProvider
from taxes.providers.base import TaxProvider
from taxes.providers.manual import ManualTaxProvider
from taxes.providers.taxjar import TaxJarProvider


def get_tax_provider(provider: str | None = None) -> TaxProvider:
    provider_slug = (provider or getattr(settings, "TAX_PROVIDER", "manual") or "manual").lower().strip()
    if provider_slug == ManualTaxProvider.slug:
        return ManualTaxProvider()
    if provider_slug == TaxJarProvider.slug:
        return TaxJarProvider()
    if provider_slug == AvalaraProvider.slug:
        return AvalaraProvider()
    raise ValueError(f"Unsupported tax provider: {provider_slug}")


def get_fallback_tax_provider() -> TaxProvider:
    fallback = (getattr(settings, "TAX_FALLBACK_PROVIDER", "manual") or "manual").lower().strip()
    return get_tax_provider(fallback)

