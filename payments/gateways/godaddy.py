from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.conf import settings

from core.runtime_settings import get_runtime_setting
from payments.gateways.base import PaymentGateway, PaymentSession, PaymentVerificationResult, RefundResult
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


class GoDaddyPaymentGateway(PaymentGateway):
    slug = "godaddy"

    _CONFIRMED_STATUSES = {"captured", "confirmed", "succeeded", "success", "paid"}
    _FAILED_STATUSES = {"failed", "declined", "canceled", "cancelled", "voided", "error"}

    def _runtime(self, key: str, default: str = "") -> str:
        return str(get_runtime_setting(key, getattr(settings, key.upper(), default) or default)).strip()

    def _base_url(self) -> str:
        base_url = self._runtime("godaddy_payments_base_url", "")
        if not base_url:
            raise ValueError("GoDaddy payments base URL is not configured.")
        return base_url.rstrip("/") + "/"

    def _merchant_id(self) -> str:
        return self._runtime("godaddy_merchant_id", "")

    def _api_key(self) -> str:
        return self._runtime("godaddy_api_key", "")

    def _api_secret(self) -> str:
        return self._runtime("godaddy_api_secret", "")

    def _build_headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("GoDaddy API key is not configured.")

        # GoDaddy REST API uses sso-key {KEY}:{SECRET} when a secret is configured.
        # Fall back to a configurable scheme (e.g. Bearer) for alternative auth flows.
        api_secret = self._api_secret()
        if api_secret:
            auth_value = f"sso-key {api_key}:{api_secret}"
        else:
            auth_scheme = self._runtime("godaddy_payments_auth_scheme", "sso-key") or "sso-key"
            auth_value = f"{auth_scheme} {api_key}"

        headers = {
            "Authorization": auth_value,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        merchant_id = self._merchant_id()
        if merchant_id:
            headers["X-Merchant-Id"] = merchant_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request_json(
        self,
        *,
        method: str,
        endpoint_path: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = float(self._runtime("godaddy_payments_timeout_seconds", "15") or "15")
        url = urljoin(self._base_url(), endpoint_path.lstrip("/"))
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(
            url=url,
            data=body,
            method=method.upper(),
            headers=self._build_headers(idempotency_key=idempotency_key),
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise ValueError(f"GoDaddy API error ({exc.code}): {error_body or exc.reason}") from exc
        except URLError as exc:
            raise ValueError(f"GoDaddy API request failed: {exc.reason}") from exc

    @staticmethod
    def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _normalize_status(cls, raw_status: str) -> str:
        status = (raw_status or "").strip().lower()
        if status in cls._CONFIRMED_STATUSES:
            return "confirmed"
        if status in cls._FAILED_STATUSES:
            return "failed"
        return status or "pending"

    def test_connection(self, *, actor=None, request=None) -> dict[str, Any]:
        test_path = self._runtime("godaddy_payments_test_path", "/v1/merchants/{merchant_id}")
        test_method = (self._runtime("godaddy_payments_test_method", "GET") or "GET").upper()
        endpoint_path = test_path.replace("{merchant_id}", self._merchant_id())
        payload = None
        if test_method != "GET":
            payload = {"merchant_id": self._merchant_id()}

        response_data = self._request_json(
            method=test_method,
            endpoint_path=endpoint_path,
            payload=payload,
        )

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy payment connection test succeeded",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "test_method": test_method,
                "test_path": endpoint_path,
            },
        )

        status = self._first_str(response_data, ("status", "state", "result")) or "ok"
        return {
            "ok": True,
            "status": status,
            "raw": response_data,
        }

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
        create_path = self._runtime("godaddy_payments_create_session_path", "/v1/payments/sessions")
        payload = {
            "order_id": str(order_id),
            "amount_cents": int(amount_cents),
            "amount": str((Decimal(int(amount_cents)) / Decimal("100")).quantize(Decimal("0.01"))),
            "currency": currency,
            "merchant_id": self._merchant_id(),
            "return_url": return_url or "",
            "cancel_url": cancel_url or "",
            "metadata": metadata or {},
        }
        response_data = self._request_json(
            method="POST",
            endpoint_path=create_path,
            payload=payload,
            idempotency_key=idempotency_key,
        )

        checkout_url = self._first_str(
            response_data,
            (
                "checkout_url",
                "checkoutUrl",
                "redirect_url",
                "redirectUrl",
                "payment_url",
                "paymentUrl",
                "url",
            ),
        )
        if not checkout_url:
            links = response_data.get("links") if isinstance(response_data.get("links"), dict) else {}
            checkout_link = links.get("checkout") if isinstance(links.get("checkout"), dict) else {}
            href = checkout_link.get("href") if isinstance(checkout_link.get("href"), str) else ""
            checkout_url = href.strip()

        provider_session_id = self._first_str(response_data, ("provider_session_id", "session_id", "checkout_session_id", "id"))
        provider_transaction_id = self._first_str(response_data, ("provider_transaction_id", "transaction_id", "payment_id", "charge_id"))

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy payment session created",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "order_id": order_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "idempotency_key": idempotency_key,
            },
        )
        return PaymentSession(
            provider=self.slug,
            provider_session_id=provider_session_id or None,
            checkout_url=checkout_url or None,
            provider_transaction_id=provider_transaction_id or None,
            raw=response_data,
        )

    def verify_payment(
        self,
        *,
        provider_transaction_id: str | None = None,
        provider_session_id: str | None = None,
        actor=None,
        request=None,
    ) -> PaymentVerificationResult:
        verify_path = self._runtime("godaddy_payments_verify_path", "/v1/payments/verify")
        verify_method = (self._runtime("godaddy_payments_verify_method", "POST") or "POST").upper()
        payload = {
            "provider_transaction_id": provider_transaction_id or "",
            "provider_session_id": provider_session_id or "",
            "merchant_id": self._merchant_id(),
        }
        response_data = self._request_json(method=verify_method, endpoint_path=verify_path, payload=payload if verify_method != "GET" else None)
        if verify_method == "GET" and (provider_transaction_id or provider_session_id):
            # Some providers support GET with ID in the path/query. Keep payload-less GET,
            # but echo useful IDs in the raw response metadata for traceability.
            response_data = {
                **response_data,
                "requested_provider_transaction_id": provider_transaction_id or "",
                "requested_provider_session_id": provider_session_id or "",
            }

        raw_status = self._first_str(response_data, ("status", "payment_status", "result", "state"))
        normalized_status = self._normalize_status(raw_status)
        provider_txn = self._first_str(response_data, ("provider_transaction_id", "transaction_id", "payment_id", "charge_id"))
        failure_code = self._first_str(response_data, ("failure_code", "error_code", "code"))
        failure_message = self._first_str(response_data, ("failure_message", "error_message", "message"))

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy payment verification requested",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "provider_transaction_id": provider_transaction_id,
                "provider_session_id": provider_session_id,
            },
        )
        return PaymentVerificationResult(
            provider=self.slug,
            is_confirmed=(normalized_status == "confirmed"),
            status=normalized_status,
            provider_transaction_id=provider_txn or provider_transaction_id,
            raw=response_data,
            failure_code=failure_code or None,
            failure_message=failure_message or None,
        )

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
        refund_path = self._runtime("godaddy_payments_refund_path", "/v1/payments/refunds")
        payload = {
            "provider_transaction_id": provider_transaction_id,
            "amount_cents": int(amount_cents) if amount_cents is not None else None,
            "currency": currency,
            "merchant_id": self._merchant_id(),
            "metadata": metadata or {},
        }
        response_data = self._request_json(
            method="POST",
            endpoint_path=refund_path,
            payload=payload,
            idempotency_key=idempotency_key,
        )

        raw_status = self._first_str(response_data, ("status", "refund_status", "result", "state"))
        normalized_status = self._normalize_status(raw_status)
        refund_id = self._first_str(response_data, ("provider_refund_id", "refund_id", "id"))
        failure_code = self._first_str(response_data, ("failure_code", "error_code", "code"))
        failure_message = self._first_str(response_data, ("failure_message", "error_message", "message"))

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy refund requested",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "provider_transaction_id": provider_transaction_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "idempotency_key": idempotency_key,
            },
        )
        return RefundResult(
            provider=self.slug,
            status=normalized_status,
            provider_refund_id=refund_id or None,
            raw=response_data,
            failure_code=failure_code or None,
            failure_message=failure_message or None,
        )

    def verify_webhook_signature(self, *, body: bytes, headers: dict[str, str]) -> bool:
        secret = (
            get_runtime_setting("godaddy_payments_webhook_secret", getattr(settings, "GODADDY_PAYMENTS_WEBHOOK_SECRET", "") or getattr(settings, "PAYMENTS_WEBHOOK_SECRET", ""))
        ).strip()
        if not secret:
            return True

        # Accept common signature header keys.
        signature = ""
        for key in ("X-GoDaddy-Signature", "X-Godaddy-Signature", "X-Signature", "X-Webhook-Signature"):
            header_value = headers.get(key) or headers.get(key.lower())
            if header_value:
                signature = str(header_value).strip()
                break
        if not signature:
            return False

        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        provided = signature.split("=")[-1].strip()
        return hmac.compare_digest(expected, provided)

    def extract_provider_ids_from_webhook(self, *, payload: dict[str, Any]) -> dict[str, str]:
        ids = super().extract_provider_ids_from_webhook(payload=payload)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        if "provider_transaction_id" not in ids:
            tx_id = self._first_str(data, ("transaction_id", "payment_id", "charge_id"))
            if tx_id:
                ids["provider_transaction_id"] = tx_id

        if "provider_session_id" not in ids:
            session_id = self._first_str(data, ("session_id", "checkout_session_id"))
            if session_id:
                ids["provider_session_id"] = session_id

        if "order_id" not in ids:
            order_id = data.get("order_id")
            if isinstance(order_id, (str, int)) and str(order_id):
                ids["order_id"] = str(order_id)

        return ids
