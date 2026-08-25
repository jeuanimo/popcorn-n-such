from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings

from core.runtime_settings import get_runtime_setting
from payments.gateways.base import PaymentGateway, PaymentSession, PaymentVerificationResult, RefundResult
from payments.gateways.poynt_auth import (
    PoyntAPIError,
    PoyntAuthError,
    PoyntClient,
    PoyntConfigurationError,
    PoyntTimeoutError,
    describe_configuration,
    is_configured,
)
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

logger = logging.getLogger("payments.godaddy")


class GoDaddyPaymentGateway(PaymentGateway):
    slug = "godaddy"
    _BUSINESS_ID_PLACEHOLDER = "{business_id}"

    _CONFIRMED_STATUSES = {"captured", "confirmed", "succeeded", "success", "paid", "authorized"}
    _FAILED_STATUSES = {"failed", "declined", "canceled", "cancelled", "voided", "error"}

    def _runtime(self, key: str, default: str = "") -> str:
        return str(get_runtime_setting(key, getattr(settings, key.upper(), default) or default)).strip()

    def _base_url(self) -> str:
        base_url = self._runtime("godaddy_payments_base_url", "")
        if not base_url:
            raise ValueError("GoDaddy payments base URL is not configured.")
        return base_url.rstrip("/") + "/"

    def _services_base_url(self) -> str:
        base_url = self._runtime("godaddy_services_base_url", "https://services.poynt.net")
        if not base_url:
            raise ValueError("GoDaddy services base URL is not configured.")
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
        url = self._validated_url(base_url=self._base_url(), endpoint_path=endpoint_path)
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
            # nosec B310 - URL scheme is restricted to http/https by _validated_url.
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise ValueError(f"GoDaddy API error ({exc.code}): {error_body or exc.reason}") from exc
        except URLError as exc:
            raise ValueError(f"GoDaddy API request failed: {exc.reason}") from exc

    def _request_services_json(
        self,
        *,
        method: str,
        endpoint_path: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        timeout_seconds = float(self._runtime("godaddy_payments_timeout_seconds", "15") or "15")
        url = self._validated_url(base_url=self._services_base_url(), endpoint_path=endpoint_path)
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
            # nosec B310 - URL scheme is restricted to http/https by _validated_url.
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise ValueError(f"GoDaddy services API error ({exc.code}): {error_body or exc.reason}") from exc
        except URLError as exc:
            raise ValueError(f"GoDaddy services API request failed: {exc.reason}") from exc

    @staticmethod
    def _validated_url(*, base_url: str, endpoint_path: str) -> str:
        url = urljoin(base_url, endpoint_path.lstrip("/"))
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            raise ValueError("Unsupported URL scheme for payment provider request.")
        return url

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

    @staticmethod
    def _amount_payload(*, amount_cents: int, currency: str) -> dict[str, Any]:
        return {
            "amount_cents": int(amount_cents),
            "amount": str((Decimal(int(amount_cents)) / Decimal("100")).quantize(Decimal("0.01"))),
            "currency": currency,
        }

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

    # ------------------------------------------------------------------
    # Poynt Collect flow (server-side half)
    #
    # Documented sequence:  nonce -> payment token -> charge
    # The browser SDK produces a single-use nonce; the server exchanges it for
    # a payment token, then charges that token. Endpoint paths come from pinned
    # settings, never from staff-editable runtime settings.
    # ------------------------------------------------------------------

    def _poynt_client(self) -> PoyntClient:
        return PoyntClient()

    def _resolve_business_id(self, business_id: str | None = None) -> str:
        resolved = (
            business_id
            or (getattr(settings, "GODADDY_POYNT_BUSINESS_ID", "") or "").strip()
            or self._runtime("godaddy_collect_business_id", "")
            or self._merchant_id()
        ).strip()
        if not resolved:
            raise ValueError("A GoDaddy/Poynt Business ID is required for payment requests.")
        return resolved

    def _resolve_store_id(self, store_id: str | None = None) -> str:
        return (store_id or (getattr(settings, "GODADDY_POYNT_STORE_ID", "") or "").strip()).strip()

    @staticmethod
    def _resolve_action(action: str | None) -> str:
        """
        SALE authorises and captures in one call — the correct action for a
        normal e-commerce checkout. AUTHORIZE defers capture to a later call.
        """
        resolved = (action or getattr(settings, "GODADDY_PAYMENTS_CHARGE_ACTION", "SALE") or "SALE").strip().upper()
        return resolved if resolved in {"SALE", "AUTHORIZE"} else "SALE"

    def _charge_path(self, business_id: str) -> str:
        return settings.GODADDY_POYNT_CHARGE_PATH.format(business_id=business_id)

    def _tokenize_path(self, business_id: str) -> str:
        return settings.GODADDY_POYNT_TOKENIZE_PATH.format(business_id=business_id)

    @staticmethod
    def _card_details(response_data: dict[str, Any]) -> dict[str, str]:
        """
        Extract PCI-safe card descriptors from a tokenize/charge response.

        Only brand and last four digits are kept. PAN, CVV and expiry are
        explicitly ignored even when the provider returns them.
        """
        card = response_data.get("card") if isinstance(response_data.get("card"), dict) else {}
        if not card:
            funding = response_data.get("fundingSource") if isinstance(response_data.get("fundingSource"), dict) else {}
            card = funding.get("card") if isinstance(funding.get("card"), dict) else {}

        avs = response_data.get("avsResponse") if isinstance(response_data.get("avsResponse"), dict) else {}
        return {
            "card_brand": str(card.get("type") or "").strip()[:32],
            "card_last4": str(card.get("numberLast4") or "").strip()[:4],
            "avs_result": str(avs.get("addressResult") or "").strip()[:32],
            "cvv_result": str(response_data.get("cvvResponse") or "").strip()[:32],
        }

    def create_payment_token(
        self,
        *,
        nonce: str,
        idempotency_key: str,
        business_id: str | None = None,
        actor=None,
        request=None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Exchange a single-use Poynt Collect nonce for a reusable payment token.

        POST /businesses/{businessId}/cards/tokenize   body: {"nonce": "..."}
        """
        resolved_business_id = self._resolve_business_id(business_id)
        response_data = self._poynt_client().request(
            method="POST",
            endpoint_path=self._tokenize_path(resolved_business_id),
            json_body={"nonce": nonce},
            # Tokenizing does not move money, so a distinct id per attempt is fine.
            request_id=f"{idempotency_key}-tok",
        )

        payment_token = self._first_str(response_data, ("paymentToken", "token"))
        card_details = self._card_details(response_data)

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy payment token created",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "business_id": resolved_business_id,
                "token_status": self._first_str(response_data, ("status",)),
                **card_details,
            },
        )
        return {
            "payment_token": payment_token,
            "status": self._first_str(response_data, ("status",)),
            "raw": response_data,
            **card_details,
        }

    def charge_payment_token(
        self,
        *,
        payment_token: str,
        amount_cents: int,
        currency: str,
        idempotency_key: str,
        action: str | None = None,
        auth_only: bool | None = None,
        business_id: str | None = None,
        store_id: str | None = None,
        email_receipt: bool = False,
        receipt_email_address: str = "",
        actor=None,
        request=None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentVerificationResult:
        """
        Charge a payment token.

        POST /businesses/{businessId}/cards/tokenize/charge

        `idempotency_key` is sent as Poynt-Request-Id. Replaying the same key
        returns the original transaction instead of charging a second time,
        which is what makes safe retry possible.
        """
        resolved_business_id = self._resolve_business_id(business_id)
        resolved_action = self._resolve_action(action)

        payload: dict[str, Any] = {
            "action": resolved_action,
            "context": {"businessId": resolved_business_id},
            "amounts": {
                "transactionAmount": int(amount_cents),
                "orderAmount": int(amount_cents),
                "currency": currency,
            },
            "fundingSource": {"cardToken": payment_token},
        }
        resolved_store_id = self._resolve_store_id(store_id)
        if resolved_store_id:
            payload["context"]["storeId"] = resolved_store_id
        if resolved_action == "AUTHORIZE":
            payload["authOnly"] = True if auth_only is None else bool(auth_only)
        if email_receipt and receipt_email_address:
            payload["emailReceipt"] = True
            payload["receiptEmailAddress"] = receipt_email_address
        if metadata:
            payload["metadata"] = metadata

        response_data = self._poynt_client().request(
            method="POST",
            endpoint_path=self._charge_path(resolved_business_id),
            json_body=payload,
            request_id=idempotency_key,
        )
        return self._build_charge_result(
            response_data,
            action=resolved_action,
            amount_cents=amount_cents,
            currency=currency,
            idempotency_key=idempotency_key,
            actor=actor,
            request=request,
        )

    def charge_nonce(
        self,
        *,
        nonce: str,
        amount_cents: int,
        currency: str,
        idempotency_key: str,
        action: str | None = None,
        auth_only: bool | None = None,
        business_id: str | None = None,
        store_id: str | None = None,
        email_receipt: bool = False,
        receipt_email_address: str = "",
        actor=None,
        request=None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentVerificationResult:
        """
        Charge a Poynt Collect nonce.

        GoDaddy documents no direct nonce->charge endpoint, so this performs the
        documented two-step exchange (tokenize, then charge the token) and
        returns the charge result. Card descriptors captured during tokenization
        are merged into the result's raw payload for storage.
        """
        token_details = self.create_payment_token(
            nonce=nonce,
            idempotency_key=idempotency_key,
            business_id=business_id,
            actor=actor,
            request=request,
            metadata=metadata,
        )
        payment_token = token_details.get("payment_token") or ""
        if not payment_token:
            return PaymentVerificationResult(
                provider=self.slug,
                is_confirmed=False,
                status="failed",
                provider_transaction_id=None,
                raw=token_details.get("raw") or {},
                failure_code="tokenization_failed",
                failure_message="The card could not be tokenized. Please re-enter your card details.",
            )

        result = self.charge_payment_token(
            payment_token=payment_token,
            amount_cents=amount_cents,
            currency=currency,
            idempotency_key=idempotency_key,
            action=action,
            auth_only=auth_only,
            business_id=business_id,
            store_id=store_id,
            email_receipt=email_receipt,
            receipt_email_address=receipt_email_address,
            actor=actor,
            request=request,
            metadata=metadata,
        )

        # Preserve tokenization-time card descriptors (AVS/CVV are only
        # returned on the tokenize call) alongside the charge response.
        merged_raw = dict(result.raw or {})
        merged_raw["_card_details"] = {
            key: token_details.get(key, "")
            for key in ("card_brand", "card_last4", "avs_result", "cvv_result")
        }
        return replace(result, raw=merged_raw)

    def _extract_nonce_charge_details(self, response_data: dict[str, Any]) -> tuple[str, str, str]:
        """Pull the transaction id and any failure detail out of a charge response."""
        provider_txn = self._first_str(
            response_data,
            ("provider_transaction_id", "transaction_id", "payment_id", "charge_id", "id"),
        )
        processor_response = (
            response_data.get("processorResponse")
            if isinstance(response_data.get("processorResponse"), dict)
            else {}
        )
        if not provider_txn:
            provider_txn = self._first_str(processor_response, ("transactionId", "id"))

        failure_code = self._first_str(response_data, ("failure_code", "error_code", "code"))
        if not failure_code:
            failure_code = self._first_str(processor_response, ("statusCode", "code"))

        failure_message = self._first_str(response_data, ("failure_message", "error_message", "message"))
        if not failure_message:
            failure_message = self._first_str(processor_response, ("statusMessage", "status"))
        return provider_txn, failure_code, failure_message

    def _build_charge_result(
        self,
        response_data: dict[str, Any],
        *,
        action: str,
        amount_cents: int,
        currency: str,
        idempotency_key: str,
        actor=None,
        request=None,
    ) -> PaymentVerificationResult:
        raw_status = self._first_str(response_data, ("status", "payment_status", "result", "state"))
        normalized_status = self._normalize_status(raw_status)
        provider_txn, failure_code, failure_message = self._extract_nonce_charge_details(response_data)

        # An AUTHORIZE-only transaction is authorised but not captured; it must
        # not be treated as a completed payment for a normal storefront order.
        is_confirmed = normalized_status == "confirmed"
        if action == "AUTHORIZE":
            is_confirmed = False

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy card charge completed",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "idempotency_key": idempotency_key,
                "amount_cents": amount_cents,
                "currency": currency,
                "action": action,
                "status": normalized_status,
                "provider_transaction_id": provider_txn,
                **self._card_details(response_data),
            },
        )
        return PaymentVerificationResult(
            provider=self.slug,
            is_confirmed=is_confirmed,
            status=normalized_status,
            provider_transaction_id=provider_txn or None,
            raw=response_data,
            failure_code=failure_code or None,
            failure_message=failure_message or None,
        )

    def get_transaction(self, *, transaction_id: str, business_id: str | None = None) -> dict[str, Any]:
        """
        Fetch a single transaction by its provider id.

        GET /businesses/{businessId}/transactions/{transactionId}

        Read-only and safe to retry — this is the primary tool for resolving an
        ambiguous charge outcome without risking a second charge.
        """
        resolved_business_id = self._resolve_business_id(business_id)
        path = settings.GODADDY_POYNT_TRANSACTION_PATH.format(
            business_id=resolved_business_id,
            transaction_id=transaction_id,
        )
        return self._poynt_client().request(method="GET", endpoint_path=path, idempotent=True)

    def find_transactions(self, *, business_id: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        List transactions for the business.

        GET /businesses/{businessId}/transactions

        Used by reconciliation to locate a charge whose id was never received
        because the connection dropped before the response arrived.
        """
        resolved_business_id = self._resolve_business_id(business_id)
        path = settings.GODADDY_POYNT_TRANSACTIONS_PATH.format(business_id=resolved_business_id)
        if params:
            path = f"{path}?{urlencode(params)}"
        return self._poynt_client().request(method="GET", endpoint_path=path, idempotent=True)

    def refund_transaction(
        self,
        *,
        provider_transaction_id: str,
        amount_cents: int | None = None,
        currency: str = "USD",
        idempotency_key: str | None = None,
        business_id: str | None = None,
        actor=None,
        request=None,
    ) -> RefundResult:
        """
        Refund a settled transaction, fully or partially.

        POST /businesses/{businessId}/transactions
            {"action": "REFUND", "parentId": "<original transaction id>",
             "amounts": {...}}   # amounts omitted => full refund

        A refund is recorded by the provider as its own transaction referencing
        the original via parentId; the original is never modified or deleted.
        """
        resolved_business_id = self._resolve_business_id(business_id)
        payload: dict[str, Any] = {
            "action": "REFUND",
            "parentId": provider_transaction_id,
        }
        if amount_cents is not None:
            payload["amounts"] = {
                "transactionAmount": int(amount_cents),
                "orderAmount": int(amount_cents),
                "tipAmount": 0,
                "currency": currency,
            }

        response_data = self._poynt_client().request(
            method="POST",
            endpoint_path=settings.GODADDY_POYNT_TRANSACTIONS_PATH.format(
                business_id=resolved_business_id
            ),
            json_body=payload,
            request_id=idempotency_key,
        )

        raw_status = self._first_str(response_data, ("status", "state"))
        normalized_status = self._normalize_status(raw_status)
        refund_id = self._first_str(response_data, ("id", "refund_id"))

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy refund processed",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "parent_transaction_id": provider_transaction_id,
                "refund_transaction_id": refund_id,
                "amount_cents": amount_cents,
                "currency": currency,
                "status": raw_status,
                "idempotency_key": idempotency_key,
            },
        )
        return RefundResult(
            provider=self.slug,
            # Poynt reports a successful refund as status REFUNDED.
            status="refunded" if raw_status.strip().upper() == "REFUNDED" else normalized_status,
            provider_refund_id=refund_id or None,
            raw=response_data,
            failure_code=self._first_str(response_data, ("failure_code", "code")) or None,
            failure_message=self._first_str(response_data, ("failure_message", "message")) or None,
        )

    def void_transaction(
        self,
        *,
        provider_transaction_id: str,
        idempotency_key: str | None = None,
        business_id: str | None = None,
        actor=None,
        request=None,
    ) -> RefundResult:
        """
        Void an authorization that has not yet settled.

        POST /businesses/{businessId}/transactions/{transactionId}/void

        Voiding is preferable to refunding when the transaction has not settled,
        because it releases the hold rather than moving money back.
        """
        resolved_business_id = self._resolve_business_id(business_id)
        response_data = self._poynt_client().request(
            method="POST",
            endpoint_path=(
                f"/businesses/{resolved_business_id}/transactions/"
                f"{provider_transaction_id}/void"
            ),
            request_id=idempotency_key,
        )
        raw_status = self._first_str(response_data, ("status", "state"))

        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy transaction voided",
            actor=actor,
            request=request,
            metadata={
                "provider": self.slug,
                "provider_transaction_id": provider_transaction_id,
                "status": raw_status,
                "idempotency_key": idempotency_key,
            },
        )
        return RefundResult(
            provider=self.slug,
            status="cancelled" if raw_status.strip().upper() == "VOIDED" else self._normalize_status(raw_status),
            provider_refund_id=self._first_str(response_data, ("id",)) or None,
            raw=response_data,
        )

    def test_poynt_connection(self, *, actor=None, request=None) -> dict[str, Any]:
        """Authenticate and make one harmless read to prove credentials work."""
        client = self._poynt_client()
        client.get_access_token(force_refresh=True)
        business_id = self._resolve_business_id()
        client.request(
            method="GET",
            endpoint_path=f"/businesses/{business_id}",
            idempotent=True,
        )
        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="GoDaddy/Poynt connection test succeeded",
            actor=actor,
            request=request,
            metadata={"provider": self.slug, **describe_configuration()},
        )
        return {"ok": True, **describe_configuration()}


    def verify_webhook_signature(self, *, body: bytes, headers: dict[str, str]) -> bool:
        secret = (
            get_runtime_setting("godaddy_payments_webhook_secret", getattr(settings, "GODADDY_PAYMENTS_WEBHOOK_SECRET", "") or getattr(settings, "PAYMENTS_WEBHOOK_SECRET", ""))
        ).strip()
        if not secret:
            # Fail closed. An unsigned webhook must never be treated as
            # authentic just because no secret happens to be configured.
            logger.error("Rejecting GoDaddy webhook: no webhook secret is configured")
            return False

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
