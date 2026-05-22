from __future__ import annotations

from dataclasses import asdict
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from orders.models import OrderStatus
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from taxes.models import TaxCalculation
from taxes.providers.base import ShippingAddress, TaxQuoteRequest
from taxes.registry import get_fallback_tax_provider, get_tax_provider


def validate_shipping_address(*, address: ShippingAddress, provider: str | None = None, actor=None, django_request=None) -> dict[str, Any]:
    gateway = get_tax_provider(provider)
    is_valid, normalized = gateway.validate_address(address=address)
    if not is_valid:
        raise ValidationError("Shipping address could not be validated.")
    return normalized or {}


def _order_is_paid(order) -> bool:
    return getattr(order, "status", "") in {OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PACKED, OrderStatus.SHIPPED, OrderStatus.DELIVERED}


@transaction.atomic
def calculate_tax_for_cart(
    *,
    cart,
    address: ShippingAddress,
    taxable_subtotal_cents: int,
    shipping_cents: int,
    currency: str = "USD",
    provider: str | None = None,
    actor=None,
    django_request=None,
    allow_fallback: bool = True,
) -> TaxCalculation:
    tax_provider = get_tax_provider(provider)
    request = TaxQuoteRequest(
        taxable_subtotal_cents=int(taxable_subtotal_cents),
        shipping_cents=int(shipping_cents),
        destination=address,
        currency=currency,
        cart_id=cart.id,
    )
    try:
        result = tax_provider.calculate_tax(request, actor=actor, django_request=django_request)
    except Exception as exc:  # noqa: BLE001
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Tax provider failure",
            actor=actor,
            request=django_request,
            metadata={
                "provider": getattr(tax_provider, "slug", "unknown"),
                "cart_id": cart.id,
                "error": str(exc),
            },
        )
        if not allow_fallback:
            raise
        fallback = get_fallback_tax_provider()
        result = fallback.calculate_tax(request, actor=actor, django_request=django_request)
        result = type(result)(**{**asdict(result), "is_fallback": True})  # dataclass copy w/ flag

    calc = TaxCalculation.objects.create(
        cart=cart,
        provider=result.provider,
        provider_reference_id=result.provider_reference_id or "",
        shipping_address_line_1=address.address_line_1,
        shipping_address_line_2=address.address_line_2,
        shipping_city=address.city,
        shipping_state=address.state,
        shipping_postal_code=address.postal_code,
        shipping_country=address.country,
        taxable_subtotal_cents=int(taxable_subtotal_cents),
        shipping_cents=int(shipping_cents),
        tax_cents=max(int(result.tax_cents), 0),
        currency=currency,
        jurisdiction_data=result.jurisdiction or {},
        provider_metadata=result.raw or {},
        succeeded=(result.status == "calculated"),
        failure_code=result.failure_code or "",
        failure_message=result.failure_message or "",
        calculated_by=actor if getattr(actor, "is_authenticated", False) else None,
        is_final=False,
    )
    return calc


@transaction.atomic
def calculate_tax_for_order(
    *,
    order,
    provider: str | None = None,
    actor=None,
    django_request=None,
    allow_fallback: bool = True,
    force_recalculate: bool = False,
) -> TaxCalculation:
    if _order_is_paid(order) and not force_recalculate:
        raise ValidationError("Tax cannot be recalculated after payment without a controlled adjustment.")

    address = ShippingAddress(
        address_line_1=order.shipping_address_line_1,
        address_line_2=order.shipping_address_line_2,
        city=order.shipping_city,
        state=order.shipping_state,
        postal_code=order.shipping_postal_code,
        country=order.shipping_country,
    )
    tax_provider = get_tax_provider(provider)
    request = TaxQuoteRequest(
        taxable_subtotal_cents=int(order.subtotal_cents),
        shipping_cents=int(order.shipping_cents),
        destination=address,
        currency="USD",
        order_id=order.id,
    )

    try:
        result = tax_provider.calculate_tax(request, actor=actor, django_request=django_request)
    except Exception as exc:  # noqa: BLE001
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Tax provider failure",
            actor=actor,
            request=django_request,
            metadata={
                "provider": getattr(tax_provider, "slug", "unknown"),
                "order_id": order.id,
                "error": str(exc),
            },
        )
        if not allow_fallback:
            raise
        fallback = get_fallback_tax_provider()
        result = fallback.calculate_tax(request, actor=actor, django_request=django_request)
        result = type(result)(**{**asdict(result), "is_fallback": True})

    calc = TaxCalculation.objects.create(
        order=order,
        provider=result.provider,
        provider_reference_id=result.provider_reference_id or "",
        shipping_address_line_1=address.address_line_1,
        shipping_address_line_2=address.address_line_2,
        shipping_city=address.city,
        shipping_state=address.state,
        shipping_postal_code=address.postal_code,
        shipping_country=address.country,
        taxable_subtotal_cents=int(order.subtotal_cents),
        shipping_cents=int(order.shipping_cents),
        tax_cents=max(int(result.tax_cents), 0),
        currency="USD",
        jurisdiction_data=result.jurisdiction or {},
        provider_metadata=result.raw or {},
        succeeded=(result.status == "calculated"),
        failure_code=result.failure_code or "",
        failure_message=result.failure_message or "",
        calculated_by=actor if getattr(actor, "is_authenticated", False) else None,
        is_final=_order_is_paid(order),
    )

    # Server-side authoritative persistence back onto the order (unless already paid and we're forcing).
    order.tax_cents = calc.tax_cents
    order.total_cents = int(order.subtotal_cents) + int(order.shipping_cents) + int(order.tax_cents) - int(getattr(order, "discount_cents", 0))
    order.save(update_fields=["tax_cents", "total_cents", "updated_at"])

    return calc


@transaction.atomic
def finalize_tax_snapshot_for_paid_order(*, order, actor=None, django_request=None) -> TaxCalculation | None:
    """
    After payment confirmation, persist a final tax snapshot if none exists.
    """
    existing = order.tax_calculations.filter(is_final=True).first()
    if existing:
        return existing

    calc = TaxCalculation.objects.create(
        order=order,
        provider=getattr(order, "tax_provider", "") or "manual",
        provider_reference_id="",
        shipping_address_line_1=order.shipping_address_line_1,
        shipping_address_line_2=order.shipping_address_line_2,
        shipping_city=order.shipping_city,
        shipping_state=order.shipping_state,
        shipping_postal_code=order.shipping_postal_code,
        shipping_country=order.shipping_country,
        taxable_subtotal_cents=int(order.subtotal_cents),
        shipping_cents=int(order.shipping_cents),
        tax_cents=int(order.tax_cents),
        currency="USD",
        jurisdiction_data={},
        provider_metadata={"finalized_from_order": True, "finalized_at": timezone.now().isoformat()},
        succeeded=True,
        calculated_by=actor if getattr(actor, "is_authenticated", False) else None,
        is_final=True,
    )
    return calc

