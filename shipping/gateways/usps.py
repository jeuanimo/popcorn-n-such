from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from shipping.carriers.base import AddressInput, LabelRequest, LabelResult, RateQuote, RateRequest, ValidationResult
from shipping.gateways.base import ShippingProvider


class USPSProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class USPSOAuthToken:
    access_token: str
    token_type: str
    expires_at: float
    raw: dict[str, Any]


class USPSProvider(ShippingProvider):
    """
    USPS direct integration (modern API-ready, not legacy Web Tools).

    This is a scaffolding provider:
    - OAuth handling is structured but endpoints/claims must be filled in with USPS docs.
    - Response parsing is intentionally conservative; raw responses are returned for persistence.
    - Do NOT call real USPS endpoints in tests; mock `_http_request`/`_request_json`.
    """

    slug = "usps"

    @property
    def env(self) -> str:
        return (getattr(settings, "USPS_ENV", "") or os.getenv("USPS_ENV", "sandbox")).lower().strip()

    @property
    def client_id(self) -> str:
        return (getattr(settings, "USPS_CLIENT_ID", "") or os.getenv("USPS_CLIENT_ID", "")).strip()

    @property
    def client_secret(self) -> str:
        return (getattr(settings, "USPS_CLIENT_SECRET", "") or os.getenv("USPS_CLIENT_SECRET", "")).strip()

    @property
    def base_url(self) -> str:
        # Insert USPS modern API base URLs here (sandbox/prod).
        if self.env in {"prod", "production", "live"}:
            return (getattr(settings, "USPS_BASE_URL_PROD", "") or os.getenv("USPS_BASE_URL_PROD", "")).strip() or "https://api.usps.com"  # noqa: S105
        return (getattr(settings, "USPS_BASE_URL_SANDBOX", "") or os.getenv("USPS_BASE_URL_SANDBOX", "")).strip() or "https://api.sandbox.usps.com"  # noqa: S105

    @property
    def _oauth_cache_key(self) -> str:
        return f"shipping:usps:oauth_token:{self.env}"

    def _http_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: int = 20,
    ) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(url, data=body, method=method.upper())
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                status = int(getattr(resp, "status", 200))
                resp_headers = {k: v for k, v in resp.headers.items()}
                data = resp.read() or b""
                return status, resp_headers, data
        except urllib.error.HTTPError as exc:
            data = exc.read() if hasattr(exc, "read") else b""
            resp_headers = dict(getattr(exc, "headers", {}) or {})
            return int(getattr(exc, "code", 500)), resp_headers, data
        except urllib.error.URLError as exc:
            raise USPSProviderError(f"Network error calling USPS: {exc}") from exc

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        actor=None,
        django_request=None,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None

        status, resp_headers, raw_bytes = self._http_request(method=method, url=url, headers=headers, body=body)
        raw_text = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
        try:
            data = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            data = {"raw": raw_text}

        if status >= 400:
            log_audit_event(
                action=AuditAction.SECURITY_EVENT,
                message="USPS API error",
                actor=actor,
                request=django_request,
                metadata={"provider": self.slug, "status": status, "path": path, "response": data},
            )
            raise USPSProviderError(f"USPS API error ({status})")

        return {"status": status, "headers": resp_headers, "data": data}

    def _get_oauth_token(self, *, actor=None, django_request=None, force_refresh: bool = False) -> USPSOAuthToken:
        cached = None if force_refresh else cache.get(self._oauth_cache_key)
        if cached:
            try:
                token = USPSOAuthToken(**cached)
                if token.expires_at - time.time() > 30:
                    return token
            except Exception:
                pass

        if not self.client_id or not self.client_secret:
            raise USPSProviderError("USPS credentials are not configured.")

        # USPS API v3 OAuth2 — client_credentials via form params (not Basic auth).
        token_url = f"{self.base_url.rstrip('/')}/oauth2/v3/token"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "addresses prices tracking labels",
        }).encode("utf-8")

        status, _, raw_bytes = self._http_request(method="POST", url=token_url, headers=headers, body=body)
        raw_text = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
        try:
            data = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            data = {"raw": raw_text}

        if status >= 400:
            log_audit_event(
                action=AuditAction.SECURITY_EVENT,
                message="USPS OAuth token error",
                actor=actor,
                request=django_request,
                metadata={"provider": self.slug, "status": status, "response": data},
            )
            raise USPSProviderError(f"USPS OAuth error ({status})")

        access_token = str(data.get("access_token") or "").strip()
        token_type = str(data.get("token_type") or "Bearer").strip()
        expires_in = int(data.get("expires_in") or 3600)
        if not access_token:
            raise USPSProviderError("USPS OAuth token response missing access_token.")

        token = USPSOAuthToken(
            access_token=access_token,
            token_type=token_type,
            expires_at=time.time() + max(expires_in, 60),
            raw=data,
        )
        cache.set(self._oauth_cache_key, token.__dict__, timeout=min(expires_in, 3600))
        return token

    # ------------------------------------------------------------------
    # ShippingProvider interface
    # ------------------------------------------------------------------

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        token = self._get_oauth_token(actor=actor, django_request=request).access_token
        # Insert real address validation endpoint path here.
        resp = self._request_json(
            method="POST",
            path="/addresses/validate",
            token=token,
            payload={
                "addressLine1": address.address_line_1,
                "addressLine2": address.address_line_2,
                "city": address.city,
                "state": address.state,
                "postalCode": address.postal_code,
                "country": address.country,
            },
            actor=actor,
            django_request=request,
        )
        raw = resp["data"]
        # Placeholder parsing.
        return ValidationResult(
            provider=self.slug,
            is_valid=True,
            is_corrected=False,
            validated_address_line_1=address.address_line_1,
            validated_address_line_2=address.address_line_2,
            validated_city=address.city,
            validated_state=address.state,
            validated_postal_code=address.postal_code,
            validated_country=address.country,
            raw=raw,
        )

    def get_shipping_options(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        weight_lbs = round(rate_request.package.weight_oz / 16.0, 4)
        resp = self._request_json(
            method="POST",
            path="/prices/v3/base-rates/search",
            token=token,
            payload={
                "originZIPCode": rate_request.from_postal_code,
                "destinationZIPCode": rate_request.to_address.postal_code,
                "weight": weight_lbs,
                "length": rate_request.package.length_in or 12.0,
                "width": rate_request.package.width_in or 8.0,
                "height": rate_request.package.height_in or 6.0,
                "mailClass": "USPS_GROUND_ADVANTAGE",
                "processingCategory": "MACHINABLE",
                "destinationEntryFacilityType": "NONE",
                "rateIndicator": "DR",
                "priceType": "RETAIL",
            },
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]
        quotes = []
        for rate in (raw.get("rates") or []):
            price_dollars = float(rate.get("price") or rate.get("totalBasePrice") or 0)
            if price_dollars <= 0:
                continue
            quotes.append(RateQuote(
                provider=self.slug,
                carrier="USPS",
                service_name=str(rate.get("description") or rate.get("mailClass") or "USPS Ground Advantage"),
                service_code=str(rate.get("mailClass") or "USPS_GROUND_ADVANTAGE"),
                rate_cents=int(round(price_dollars * 100)),
                estimated_delivery_days=None,
                provider_rate_id=str(rate.get("SKU") or rate.get("rateId") or ""),
                raw=rate,
            ))
        return quotes

    def create_domestic_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        # Insert real label purchase/creation endpoint path here.
        resp = self._request_json(
            method="POST",
            path="/labels/domestic",
            token=token,
            payload={
                "rateId": label_request.provider_rate_id,
                "from": {
                    "name": label_request.from_address.recipient_name,
                    "address1": label_request.from_address.address_line_1,
                    "address2": label_request.from_address.address_line_2,
                    "city": label_request.from_address.city,
                    "state": label_request.from_address.state,
                    "postalCode": label_request.from_address.postal_code,
                    "country": label_request.from_address.country,
                    "phone": label_request.from_address.phone,
                },
                "to": {
                    "name": label_request.to_address.recipient_name,
                    "address1": label_request.to_address.address_line_1,
                    "address2": label_request.to_address.address_line_2,
                    "city": label_request.to_address.city,
                    "state": label_request.to_address.state,
                    "postalCode": label_request.to_address.postal_code,
                    "country": label_request.to_address.country,
                    "phone": label_request.to_address.phone,
                },
                "package": {
                    "weightOz": label_request.package.weight_oz,
                    "dimensionsIn": {
                        "length": label_request.package.length_in,
                        "width": label_request.package.width_in,
                        "height": label_request.package.height_in,
                    },
                },
                "labelFormat": "PDF" if label_request.label_format == "pdf_4x6" else "ZPL",
                "referenceId": label_request.order_reference,
            },
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]
        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message="USPS label created (gateway)",
            actor=actor,
            request=django_request,
            metadata={"provider": self.slug, "order_reference": label_request.order_reference},
        )
        return LabelResult(
            provider=self.slug,
            carrier="USPS",
            service_name=str(raw.get("service") or "Priority Mail"),
            tracking_number=str(raw.get("trackingNumber") or "9400111899223412345678"),
            tracking_url=str(raw.get("trackingUrl") or "https://tools.usps.com/go/TrackConfirmAction"),
            label_format=label_request.label_format,
            label_url=str(raw.get("labelUrl") or ""),
            rate_cents=int(raw.get("rateCents") or 895),
            provider_label_id=str(raw.get("labelId") or "usps-placeholder-label-id"),
            raw=raw,
        )

    def create_return_label(self, original_provider_label_id: str, *, actor=None, django_request=None, label_format: str = "pdf_4x6") -> LabelResult:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        resp = self._request_json(
            method="POST",
            path=f"/labels/{original_provider_label_id}/return",
            token=token,
            payload={"labelFormat": "PDF" if label_format == "pdf_4x6" else "ZPL"},
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]
        return LabelResult(
            provider=self.slug,
            carrier="USPS",
            service_name="Return",
            tracking_number=str(raw.get("trackingNumber") or "return-placeholder"),
            tracking_url=str(raw.get("trackingUrl") or ""),
            label_format=label_format,
            label_url=str(raw.get("labelUrl") or ""),
            rate_cents=int(raw.get("rateCents") or 0),
            provider_label_id=str(raw.get("labelId") or "usps-return-placeholder"),
            raw=raw,
        )

    def cancel_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        resp = self._request_json(
            method="DELETE",
            path=f"/labels/{provider_label_id}",
            token=token,
            payload=None,
            actor=actor,
            django_request=django_request,
        )
        return resp["data"]

    def track_package(self, tracking_number: str, *, actor=None, django_request=None) -> dict[str, Any]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        resp = self._request_json(
            method="GET",
            path=f"/tracking/{tracking_number}",
            token=token,
            payload=None,
            actor=actor,
            django_request=django_request,
        )
        return resp["data"]

