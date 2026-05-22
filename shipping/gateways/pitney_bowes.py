from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache

from core.runtime_settings import get_runtime_setting
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from shipping.carriers.base import (
    AddressInput,
    LabelRequest,
    LabelResult,
    RateQuote,
    RateRequest,
    ValidationResult,
)


class PitneyBowesProviderError(RuntimeError):
    pass


_APP_JSON = "application/json"


# Pitney Bowes v2 carrier/service identifiers
_SERVICE_MAP: dict[str, dict[str, str]] = {
    "usps_ground": {
        "carrier": "USPS",
        "serviceId": "USPS_GROUND_ADVANTAGE",
        "display": "USPS Ground Advantage",
    },
    "fedex_ground": {
        "carrier": "FEDEX",
        "serviceId": "FEDEX_GROUND",
        "display": "FedEx Ground",
    },
    "ups_ground": {
        "carrier": "UPS",
        "serviceId": "UPS_GROUND",
        "display": "UPS Ground",
    },
}

_TRACKING_URL: dict[str, str] = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tn}",
    "FEDEX": "https://www.fedex.com/fedextrack/?trknbr={tn}",
    "UPS": "https://www.ups.com/track?tracknum={tn}",
}


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    token_type: str
    expires_at: float
    raw: dict[str, Any]


class PitneyBowesProvider:
    """
    Pitney Bowes Shipping APIs / SendPro-style integration.

    Notes:
    - This module intentionally avoids making any real network calls in tests.
    - Replace the placeholder endpoint paths with the official Pitney Bowes API URLs
      from their documentation when you're ready to integrate for real.
    - Credentials must come from env/settings; never hard-code them.
    """

    slug = "pitney_bowes"

    # ---------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------

    @property
    def env(self) -> str:
        # "sandbox" or "production"
        return str(get_runtime_setting("pitney_bowes_env", getattr(settings, "PITNEY_BOWES_ENV", "") or os.getenv("PITNEY_BOWES_ENV", "sandbox"))).lower().strip()

    @property
    def api_key(self) -> str:
        return str(get_runtime_setting("pitney_bowes_api_key", getattr(settings, "PITNEY_BOWES_API_KEY", "") or os.getenv("PITNEY_BOWES_API_KEY", ""))).strip()

    @property
    def api_secret(self) -> str:
        return str(get_runtime_setting("pitney_bowes_api_secret", getattr(settings, "PITNEY_BOWES_API_SECRET", "") or os.getenv("PITNEY_BOWES_API_SECRET", ""))).strip()

    @property
    def base_url(self) -> str:
        if self.env in {"prod", "production", "live"}:
            return str(get_runtime_setting("pitney_bowes_base_url_prod", getattr(settings, "PITNEY_BOWES_BASE_URL_PROD", "") or os.getenv("PITNEY_BOWES_BASE_URL_PROD", ""))).strip() or "https://api.sendpro360.pitneybowes.com/shipping"  # noqa: S105
        return str(get_runtime_setting("pitney_bowes_base_url_sandbox", getattr(settings, "PITNEY_BOWES_BASE_URL_SANDBOX", "") or os.getenv("PITNEY_BOWES_BASE_URL_SANDBOX", ""))).strip() or "https://api-sandbox.sendpro360.pitneybowes.com/shipping"  # noqa: S105

    @property
    def oauth_url(self) -> str:
        """SendPro 360 uses a fixed Okta token endpoint, separate from the base URL."""
        return str(
            get_runtime_setting("pitney_bowes_oauth_url", os.getenv("PITNEY_BOWES_OAUTH_URL", ""))
        ).strip() or "https://signin.pitneybowes.com/oauth2/aus1014knhTFJGfHf4h8/v1/token"  # noqa: S105

    @property
    def _oauth_cache_key(self) -> str:
        return f"shipping:pb:oauth_token:{self.env}"

    # ---------------------------------------------------------------------
    # HTTP helpers
    # ---------------------------------------------------------------------

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
                resp_headers = dict(resp.headers.items())
                data = resp.read() or b""
                return status, resp_headers, data
        except urllib.error.HTTPError as exc:
            data = exc.read() if hasattr(exc, "read") else b""
            resp_headers = dict(getattr(exc, "headers", {}) or {})
            return int(getattr(exc, "code", 500)), resp_headers, data
        except urllib.error.URLError as exc:
            raise PitneyBowesProviderError(f"Network error calling Pitney Bowes: {exc}") from exc

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
        headers = {
            "Accept": _APP_JSON,
            "Content-Type": _APP_JSON,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None

        status, resp_headers, raw_bytes = self._http_request(method=method, url=url, headers=headers, body=body)
        data = self._parse_json_bytes(raw_bytes)

        if status >= 400:
            log_audit_event(
                action=AuditAction.SECURITY_EVENT,
                message="Pitney Bowes API error",
                actor=actor,
                request=django_request,
                metadata={
                    "provider": self.slug,
                    "status": status,
                    "path": path,
                    "response": data,
                },
            )
            raise PitneyBowesProviderError(f"Pitney Bowes API error ({status})")

        return {"status": status, "headers": resp_headers, "data": data}

    # ---------------------------------------------------------------------
    # OAuth
    # ---------------------------------------------------------------------

    def _get_oauth_token(self, *, actor=None, django_request=None, force_refresh: bool = False) -> OAuthToken:
        cached = None if force_refresh else cache.get(self._oauth_cache_key)
        if cached:
            try:
                token = OAuthToken(**cached)
                if token.expires_at - time.time() > 30:
                    return token
            except Exception:
                pass

        if not self.api_key or not self.api_secret:
            raise PitneyBowesProviderError("Pitney Bowes credentials are not configured.")

        # SendPro 360 uses an Okta-hosted token endpoint with credentials in the request body.
        token_url = self.oauth_url
        headers = {
            "Accept": _APP_JSON,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.api_secret,
        }).encode("utf-8")

        status, _, raw_bytes = self._http_request(method="POST", url=token_url, headers=headers, body=body)
        data = self._parse_json_bytes(raw_bytes)

        if status >= 400:
            log_audit_event(
                action=AuditAction.SECURITY_EVENT,
                message="Pitney Bowes OAuth token error",
                actor=actor,
                request=django_request,
                metadata={"provider": self.slug, "status": status, "response": data},
            )
            raise PitneyBowesProviderError(f"Pitney Bowes OAuth error ({status})")

        token = self._build_oauth_token(data)
        cache.set(self._oauth_cache_key, token.__dict__, timeout=min(int(data.get("expires_in") or 3600), 3600))
        return token

    @staticmethod
    def _parse_json_bytes(raw_bytes: bytes) -> dict[str, Any]:
        raw_text = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
        try:
            return json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            return {"raw": raw_text}

    @staticmethod
    def _build_oauth_token(data: dict[str, Any]) -> OAuthToken:
        access_token = str(data.get("access_token") or "").strip()
        if not access_token:
            raise PitneyBowesProviderError("Pitney Bowes OAuth token response missing access_token.")
        expires_in = int(data.get("expires_in") or 3600)
        return OAuthToken(
            access_token=access_token,
            token_type=str(data.get("token_type") or "Bearer").strip(),
            expires_at=time.time() + max(expires_in, 60),
            raw=data,
        )

    # ---------------------------------------------------------------------
    # Provider methods
    # ---------------------------------------------------------------------

    def validate_address(self, address: AddressInput, *, actor=None, request=None) -> ValidationResult:
        token = self._get_oauth_token(actor=actor, django_request=request).access_token
        payload: dict[str, Any] = {
            "name": address.recipient_name,
            "addressLine1": address.address_line_1,
            "cityTown": address.city,
            "stateProvince": address.state,
            "postalCode": address.postal_code,
            "countryCode": address.country,
        }
        if address.address_line_2:
            payload["addressLine2"] = address.address_line_2
        resp = self._request_json(
            method="POST",
            path="/api/v1/address/verify",
            token=token,
            payload=payload,
            actor=actor,
            django_request=request,
        )
        raw = resp["data"]
        # Placeholder parsing; replace with Pitney Bowes response fields.
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

    def get_rates(self, rate_request: RateRequest, *, actor=None, django_request=None) -> list[RateQuote]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token

        to_addr = rate_request.to_address
        to_block: dict[str, Any] = {
            "addressLine1": to_addr.address_line_1,
            "cityTown": to_addr.city,
            "stateProvince": to_addr.state,
            "postalCode": to_addr.postal_code,
            "countryCode": to_addr.country,
        }
        if to_addr.address_line_2:
            to_block["addressLine2"] = to_addr.address_line_2
        payload: dict[str, Any] = {
            "fromAddress": {
                "postalCode": rate_request.from_postal_code,
                "countryCode": rate_request.from_country,
            },
            "toAddress": to_block,
            "parcel": {
                "weight": {
                    "unitOfMeasurement": "OZ",
                    "weight": rate_request.package.weight_oz,
                },
            },
            "rates": [{"carrier": "USPS", "parcelType": "PKG"}],
        }
        if rate_request.package.length_in or rate_request.package.width_in or rate_request.package.height_in:
            payload["parcel"]["dimension"] = {
                "unitOfMeasurement": "IN",
                "length": rate_request.package.length_in,
                "width": rate_request.package.width_in,
                "height": rate_request.package.height_in,
            }

        resp = self._request_json(
            method="POST",
            path="/api/v1/rates",
            token=token,
            payload=payload,
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]

        rate_list = raw.get("rates") or []
        if not isinstance(rate_list, list):
            rate_list = []
        return [q for rate in rate_list for q in [self._parse_rate_quote(rate)] if q is not None]

    def _parse_rate_quote(self, rate: dict[str, Any]) -> "RateQuote | None":
        charge = rate.get("totalCarrierCharge") or rate.get("baseCharge") or 0
        try:
            rate_cents = round(float(charge) * 100)
        except (TypeError, ValueError):
            return None

        commitment = rate.get("commitment") or {}
        raw_days = commitment.get("minDays") or commitment.get("maxDays")
        try:
            delivery_days: int | None = int(raw_days) if raw_days is not None else None
        except (TypeError, ValueError):
            delivery_days = None

        return RateQuote(
            provider=self.slug,
            carrier=str(rate.get("carrier") or "USPS"),
            service_name=str(rate.get("serviceName") or ""),
            service_code=str(rate.get("serviceId") or ""),
            rate_cents=rate_cents,
            currency=str(rate.get("currencyCode") or "USD"),
            estimated_delivery_days=delivery_days,
            provider_rate_id=str(rate.get("rateTypeId") or rate.get("serviceId") or ""),
            raw=rate,
        )

    def create_label(self, label_request: LabelRequest, *, actor=None, django_request=None) -> LabelResult:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        payload: dict[str, Any] = {
            "fromAddress": self._v2_address_block(label_request.from_address),
            "toAddress": self._v2_address_block(label_request.to_address),
            "parcel": self._v2_parcel_block(label_request.package),
            "documents": [
                {
                    "type": "SHIPPING_LABEL",
                    "contentType": "URL",
                    "size": "DOC_4X6",
                    "fileFormat": "PDF",
                    "printDialogOption": "NO_PRINT_DIALOG",
                }
            ],
            "referenceId": label_request.order_reference,
        }
        resp = self._request_json(
            method="POST",
            path="/api/v1/shipments",
            token=token,
            payload=payload,
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]

        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message="Pitney Bowes label created (gateway)",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "order_reference": label_request.order_reference,
                "provider_rate_id": label_request.provider_rate_id,
            },
        )

        # Placeholder parsing; replace with actual fields from PB shipment response.
        return LabelResult(
            provider=self.slug,
            carrier="USPS",
            service_name="Priority Mail",
            tracking_number="9400111899223412345678",
            tracking_url="https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223412345678",
            label_format=label_request.label_format,
            label_url="",
            rate_cents=895,
            provider_label_id=str(raw.get("shipmentId") or "pb-placeholder-shipment-id"),
            raw=raw,
        )

    # ------------------------------------------------------------------
    # v2 label creation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _v2_address_block(addr: "AddressInput") -> dict[str, Any]:
        block: dict[str, Any] = {
            "name": addr.recipient_name,
            "addressLine1": addr.address_line_1,
            "cityTown": addr.city,
            "stateProvince": addr.state,
            "postalCode": addr.postal_code,
            "countryCode": addr.country,
        }
        if addr.address_line_2:
            block["addressLine2"] = addr.address_line_2
        if addr.phone:
            block["phone"] = addr.phone
        return block

    @staticmethod
    def _v2_parcel_block(pkg: "PackageInput") -> dict[str, Any]:
        parcel: dict[str, Any] = {"weight": {"unitOfMeasurement": "OZ", "weight": pkg.weight_oz}}
        if pkg.length_in or pkg.width_in or pkg.height_in:
            parcel["dimension"] = {
                "unitOfMeasurement": "IN",
                "length": pkg.length_in,
                "width": pkg.width_in,
                "height": pkg.height_in,
            }
        return parcel

    def _build_v2_payload(
        self,
        label_request: LabelRequest,
        service: dict[str, str],
        from_postal: str,
        shipper_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "fromAddress": self._v2_address_block(label_request.from_address),
            "toAddress": self._v2_address_block(label_request.to_address),
            "parcel": self._v2_parcel_block(label_request.package),
            "rates": [
                {
                    "carrier": service["carrier"],
                    "serviceId": service["serviceId"],
                    "parcelType": "PKG",
                    "inductionPostalCode": from_postal,
                }
            ],
            "documents": [
                {
                    "type": "SHIPPING_LABEL",
                    "contentType": "URL",
                    "size": "DOC_4X6",
                    "fileFormat": "PDF",
                    "printDialogOption": "NO_PRINT_DIALOG",
                },
                {
                    "type": "SHIPPING_LABEL",
                    "contentType": "BASE64",
                    "size": "DOC_4X6",
                    "fileFormat": "ZPL2",
                    "printDialogOption": "NO_PRINT_DIALOG",
                },
            ],
        }
        if shipper_id:
            payload["shipmentOptions"] = [{"name": "SHIPPER_ID", "value": shipper_id}]
        return payload

    @staticmethod
    def _parse_v2_response(raw: dict[str, Any], service: dict[str, str]) -> tuple[str, str, str, str, int]:
        """Return (shipment_id, tracking_number, carrier, service_name, rate_cents)."""
        shipment_id = str(raw.get("shipmentId") or "")
        tracking_number = str(raw.get("parcelTrackingNumber") or "")

        resp_rate = (raw.get("rates") or [{}])[0]
        total_charge = resp_rate.get("totalCarrierCharge") or resp_rate.get("baseCharge") or 0
        try:
            rate_cents = round(float(total_charge) * 100)
        except (TypeError, ValueError):
            rate_cents = 0

        carrier = str(resp_rate.get("carrier") or service["carrier"])
        service_name = str(resp_rate.get("serviceName") or service["display"])
        return shipment_id, tracking_number, carrier, service_name, rate_cents

    @staticmethod
    def _extract_label_url(raw: dict[str, Any]) -> str:
        for doc in (raw.get("documents") or []):
            if doc.get("contentType") == "URL":
                return str(doc.get("contents") or "")
        return ""

    @staticmethod
    def _extract_zpl(raw: dict[str, Any]) -> str:
        """Decode the BASE64 ZPL document from the PB v2 response, if present."""
        for doc in (raw.get("documents") or []):
            fmt = str(doc.get("fileFormat") or "").upper()
            if doc.get("contentType") == "BASE64" and "ZPL" in fmt:
                b64 = doc.get("contents") or ""
                if b64:
                    try:
                        return base64.b64decode(b64).decode("utf-8", errors="replace")
                    except Exception:
                        return ""
        return ""

    def create_label_v2(
        self,
        label_request: LabelRequest,
        *,
        carrier_key: str = "usps_ground",
        actor=None,
        django_request=None,
    ) -> LabelResult:
        """
        Create a label via the Pitney Bowes v2 Shipments endpoint.
        Requests a URL document type so the PDF can be proxied and printed in-browser.
        carrier_key must be one of: usps_ground, fedex_ground, ups_ground.
        """
        service = _SERVICE_MAP.get(carrier_key)
        if service is None:
            raise PitneyBowesProviderError(
                f"Unsupported carrier key: {carrier_key!r}. Valid: {list(_SERVICE_MAP)}"
            )

        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        shipper_id = str(
            get_runtime_setting(
                "pitney_bowes_shipper_id",
                getattr(settings, "PITNEY_BOWES_SHIPPER_ID", "") or os.getenv("PITNEY_BOWES_SHIPPER_ID", ""),
            )
        ).strip()
        from_postal = str(
            get_runtime_setting("SHIPPING_FROM_POSTAL_CODE", getattr(settings, "SHIPPING_FROM_POSTAL_CODE", "00000"))
        ).strip()

        payload = self._build_v2_payload(label_request, service, from_postal, shipper_id)
        resp = self._request_json(
            method="POST",
            path="/api/v1/shipments",
            token=token,
            payload=payload,
            actor=actor,
            django_request=django_request,
        )
        raw = resp["data"]

        shipment_id, tracking_number, carrier, service_name, rate_cents = self._parse_v2_response(raw, service)
        label_url = self._extract_label_url(raw)
        label_zpl = self._extract_zpl(raw)
        tracking_url = _TRACKING_URL.get(carrier, "").format(tn=tracking_number)

        log_audit_event(
            action=AuditAction.LABEL_CREATED,
            message=f"Pitney Bowes v2 label created: {tracking_number}",
            actor=actor,
            request=django_request,
            metadata={
                "provider": self.slug,
                "carrier": carrier,
                "service": service_name,
                "tracking_number": tracking_number,
                "shipment_id": shipment_id,
                "order_reference": label_request.order_reference,
            },
        )

        return LabelResult(
            provider=self.slug,
            carrier=carrier,
            service_name=service_name,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            label_format="pdf_4x6",
            label_url=label_url,
            label_zpl=label_zpl,
            rate_cents=rate_cents,
            provider_label_id=shipment_id,
            raw=raw,
        )

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None) -> dict[str, Any]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        # Insert real endpoint path here:
        #   DELETE /shippingservices/v1/shipments/{shipmentId}
        resp = self._request_json(
            method="DELETE",
            path=f"/api/v1/shipments/{provider_label_id}",
            token=token,
            payload=None,
            actor=actor,
            django_request=django_request,
        )
        return resp["data"]

    def track_shipment(self, tracking_number: str, *, actor=None, django_request=None) -> dict[str, Any]:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        # Insert real endpoint path here:
        #   GET /shippingservices/v1/tracking/{trackingNumber}
        resp = self._request_json(
            method="GET",
            path=f"/api/v1/tracking/{tracking_number}",
            token=token,
            payload=None,
            actor=actor,
            django_request=django_request,
        )
        return resp["data"]

    def create_return_label(
        self,
        *,
        original_provider_label_id: str,
        actor=None,
        django_request=None,
        label_format: str = "pdf_4x6",
    ) -> LabelResult:
        token = self._get_oauth_token(actor=actor, django_request=django_request).access_token
        # Insert real endpoint path here. Some providers support "return shipment" creation based on original id.
        #   POST /shippingservices/v1/shipments/{shipmentId}/return
        payload = {"labelFormat": "PDF" if label_format == "pdf_4x6" else "ZPL"}
        resp = self._request_json(
            method="POST",
            path=f"/api/v1/shipments/{original_provider_label_id}/return",
            token=token,
            payload=payload,
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
            provider_label_id=str(raw.get("shipmentId") or "pb-return-placeholder"),
            raw=raw,
        )
