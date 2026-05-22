from __future__ import annotations

from django.dispatch import Signal

payment_confirmed = Signal()
payment_failed = Signal()
payment_refunded = Signal()

