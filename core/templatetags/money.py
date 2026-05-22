from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def cents_to_dollars(value):
    try:
        cents = Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        cents = Decimal("0")
    return f"{(cents / Decimal('100')):.2f}"
