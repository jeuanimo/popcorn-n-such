from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PaymentSession:
    provider: str
    provider_session_id: str | None = None
    checkout_url: str | None = None
    provider_transaction_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class PaymentVerificationResult:
    provider: str
    is_confirmed: bool
    status: str
    provider_transaction_id: str | None = None
    raw: dict[str, Any] | None = None
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class RefundResult:
    provider: str
    status: str
    provider_refund_id: str | None = None
    raw: dict[str, Any] | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class PaymentGateway(ABC):
    slug: str

    @abstractmethod
    def create_payment_session(
        self,
        *,
        order_id: int,
        amount_cents: int,
        currency: str,
        idempotency_key: str,
        return_url: str | None = None,
        cancel_url: str | None = None,
        actor=None,
        request=None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentSession:
        raise NotImplementedError

    @abstractmethod
    def verify_payment(
        self,
        *,
        provider_transaction_id: str | None = None,
        provider_session_id: str | None = None,
        actor=None,
        request=None,
    ) -> PaymentVerificationResult:
        raise NotImplementedError

    @abstractmethod
    def refund_payment(
        self,
        *,
        provider_transaction_id: str,
        amount_cents: int | None = None,
        currency: str | None = None,
        idempotency_key: str | None = None,
        actor=None,
        request=None,
        metadata: dict[str, Any] | None = None,
    ) -> RefundResult:
        raise NotImplementedError

    def verify_webhook_signature(self, *, body: bytes, headers: dict[str, str]) -> bool:
        return False

    def extract_provider_ids_from_webhook(self, *, payload: dict[str, Any]) -> dict[str, str]:
        """
        Return any of: provider_transaction_id, provider_session_id, order_id, event_id.
        Gateways should override this with provider-specific parsing.
        """
        ids: dict[str, str] = {}
        for key in ("provider_transaction_id", "transaction_id", "payment_id", "charge_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                ids["provider_transaction_id"] = value
                break
        for key in ("provider_session_id", "session_id", "checkout_session_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                ids["provider_session_id"] = value
                break
        event_id = payload.get("event_id") or payload.get("id")
        if isinstance(event_id, str) and event_id:
            ids["event_id"] = event_id
        order_id = payload.get("order_id")
        if isinstance(order_id, (str, int)) and str(order_id):
            ids["order_id"] = str(order_id)
        return ids
