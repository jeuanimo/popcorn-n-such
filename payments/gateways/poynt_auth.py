"""
GoDaddy Payments / Poynt Commerce Platform authentication and transport.

Poynt is an OAuth 2.0 API that uses the JWT bearer assertion grant:

    Django
      ↓  build a JWT: iss=sub=applicationId, aud=<api host>, exp/iat/jti
      ↓  sign it RS256 with the application's RSA private key
      ↓  POST /token  (grantType=urn:ietf:params:oauth:grant-type:jwt-bearer)
    GoDaddy/Poynt
      ↓  accessToken (a JWT, ~24h) + refreshToken + expiresIn
    Django
      ↓  Authorization: Bearer <accessToken>  on every subsequent API call

The private key never leaves this module: it is not rendered into templates, not
returned to the browser, and never written to a log. Access tokens are likewise
never logged — only their expiry is.

Reference: https://docs.poynt.com/app-integration/cloudApps/access-token.html
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("payments.poynt")

# Cache key for the shared access token. Tokens are per (host, application),
# so a credential or environment change cannot reuse a stale token.
_TOKEN_CACHE_PREFIX = "poynt:access_token"

# Guards token minting inside a single process so a burst of concurrent
# checkouts triggers one /token round trip rather than one per request.
_token_lock = threading.Lock()


class PoyntConfigurationError(RuntimeError):
    """Raised when required Poynt credentials/settings are absent or malformed."""


class PoyntAuthError(RuntimeError):
    """Raised when Poynt rejects our credentials."""


class PoyntAPIError(RuntimeError):
    """A non-2xx response from a Poynt API endpoint."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class PoyntTimeoutError(PoyntAPIError):
    """
    The request timed out or the connection dropped.

    The charge MAY have been processed by GoDaddy. Callers must never blindly
    retry on this exception — reconcile the transaction state instead.
    """


@dataclass(frozen=True)
class PoyntCredentials:
    application_id: str
    business_id: str
    store_id: str
    private_key: str
    api_host: str
    api_version: str
    timeout_seconds: float
    token_leeway_seconds: int

    @property
    def is_production(self) -> bool:
        return self.api_host.rstrip("/") == "https://services.poynt.net"


def _read_private_key() -> str:
    """
    Resolve the RSA private key from inline setting or file path.

    Returns "" when unconfigured so that callers can render a helpful
    "not configured" state rather than crashing at import time.
    """
    inline = (getattr(settings, "GODADDY_POYNT_PRIVATE_KEY", "") or "").strip()
    if inline:
        return inline

    key_path = (getattr(settings, "GODADDY_POYNT_PRIVATE_KEY_PATH", "") or "").strip()
    if not key_path:
        return ""
    try:
        with open(key_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as exc:
        # Deliberately does not include the key path contents.
        raise PoyntConfigurationError(f"Could not read Poynt private key file: {exc.strerror}") from exc


def get_credentials() -> PoyntCredentials:
    return PoyntCredentials(
        application_id=(getattr(settings, "GODADDY_POYNT_APPLICATION_ID", "") or "").strip(),
        business_id=(getattr(settings, "GODADDY_POYNT_BUSINESS_ID", "") or "").strip(),
        store_id=(getattr(settings, "GODADDY_POYNT_STORE_ID", "") or "").strip(),
        private_key=_read_private_key(),
        api_host=(getattr(settings, "GODADDY_POYNT_API_HOST", "") or "").strip().rstrip("/"),
        api_version=(getattr(settings, "GODADDY_POYNT_API_VERSION", "1.2") or "1.2").strip(),
        timeout_seconds=float(getattr(settings, "GODADDY_POYNT_TIMEOUT_SECONDS", 20)),
        token_leeway_seconds=int(getattr(settings, "GODADDY_POYNT_TOKEN_LEEWAY_SECONDS", 300)),
    )


def is_configured() -> bool:
    """True when enough credentials exist to attempt a server-side API call."""
    creds = get_credentials()
    return bool(creds.application_id and creds.business_id and creds.private_key and creds.api_host)


def describe_configuration() -> dict[str, Any]:
    """
    Non-sensitive configuration summary for staff diagnostics pages.

    Reports only whether the private key is present — never any part of it.
    """
    creds = get_credentials()
    return {
        "api_host": creds.api_host,
        "environment": "production" if creds.is_production else "staging/OTE",
        "is_production": creds.is_production,
        "application_id_set": bool(creds.application_id),
        "business_id_set": bool(creds.business_id),
        "store_id_set": bool(creds.store_id),
        "private_key_set": bool(creds.private_key),
        "configured": is_configured(),
    }


class PoyntClient:
    """
    Small, testable transport for the Poynt API.

    Responsibilities are limited to authentication, request signing, retries on
    expired tokens, and error normalisation. Business rules (what to charge, for
    how much, and whether an order may be paid) live in the service layer.
    """

    def __init__(self, credentials: PoyntCredentials | None = None):
        self.credentials = credentials or get_credentials()

    # -- token handling -------------------------------------------------------

    def _token_cache_key(self) -> str:
        host = urlparse(self.credentials.api_host).netloc or self.credentials.api_host
        return f"{_TOKEN_CACHE_PREFIX}:{host}:{self.credentials.application_id}"

    def _build_assertion(self) -> str:
        """Build and RS256-sign the self-issued JWT used as the grant assertion."""
        import jwt  # imported lazily so the app still boots without PyJWT installed

        creds = self.credentials
        if not creds.application_id:
            raise PoyntConfigurationError("GODADDY_POYNT_APPLICATION_ID is not configured.")
        if not creds.private_key:
            raise PoyntConfigurationError("GODADDY_POYNT_PRIVATE_KEY (or _PATH) is not configured.")
        if not creds.api_host:
            raise PoyntConfigurationError("GODADDY_POYNT_API_HOST is not configured.")

        now = int(time.time())
        claims = {
            "iss": creds.application_id,
            "sub": creds.application_id,
            "aud": creds.api_host,
            "iat": now,
            # Short-lived: this assertion is exchanged immediately for an access
            # token, so it never needs a long life.
            "exp": now + 300,
            "jti": str(uuid.uuid4()),
        }
        try:
            return jwt.encode(claims, creds.private_key, algorithm="RS256")
        except Exception as exc:
            # Never surface the key or its contents in the error.
            raise PoyntConfigurationError(
                f"Could not sign the Poynt authentication assertion ({type(exc).__name__}). "
                "Check that GODADDY_POYNT_PRIVATE_KEY is a valid PEM RSA private key."
            ) from exc

    def _mint_access_token(self) -> tuple[str, int]:
        """Exchange a self-signed assertion for a Poynt access token."""
        creds = self.credentials
        url = urljoin(creds.api_host + "/", settings.GODADDY_POYNT_TOKEN_PATH.lstrip("/"))
        body = urlencode(
            {
                "grantType": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._build_assertion(),
            }
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "api-version": creds.api_version,
            "Poynt-Request-Id": str(uuid.uuid4()),
        }

        try:
            response = requests.post(url, data=body, headers=headers, timeout=creds.timeout_seconds)
        except requests.Timeout as exc:
            raise PoyntTimeoutError(f"Timed out requesting a Poynt access token: {exc}") from exc
        except requests.RequestException as exc:
            raise PoyntAPIError(f"Could not reach the Poynt token endpoint: {exc}") from exc

        if response.status_code >= 400:
            # Response bodies from /token can echo the assertion — do not log it.
            logger.error(
                "Poynt token request rejected",
                extra={"status_code": response.status_code, "api_host": creds.api_host},
            )
            raise PoyntAuthError(
                f"Poynt rejected the application credentials (HTTP {response.status_code}). "
                "Verify GODADDY_POYNT_APPLICATION_ID and the private key match this environment."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise PoyntAuthError("Poynt returned a non-JSON token response.") from exc

        access_token = str(payload.get("accessToken") or "").strip()
        if not access_token:
            raise PoyntAuthError("Poynt token response did not contain an accessToken.")

        expires_in = int(payload.get("expiresIn") or 0) or 86400
        logger.info(
            "Obtained Poynt access token",
            extra={"expires_in": expires_in, "api_host": creds.api_host},
        )
        return access_token, expires_in

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """
        Return a valid access token, minting and caching one when needed.

        The cached value expires ahead of the real token (by the configured
        leeway) so a token is never used in the seconds around its expiry.
        """
        cache_key = self._token_cache_key()
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return str(cached)

        with _token_lock:
            # Another thread may have refreshed while we waited for the lock.
            if not force_refresh:
                cached = cache.get(cache_key)
                if cached:
                    return str(cached)

            access_token, expires_in = self._mint_access_token()
            leeway = self.credentials.token_leeway_seconds
            cache_ttl = max(60, expires_in - leeway)
            cache.set(cache_key, access_token, timeout=cache_ttl)
            return access_token

    def clear_cached_token(self) -> None:
        cache.delete(self._token_cache_key())

    # -- request plumbing -----------------------------------------------------

    def _build_url(self, endpoint_path: str) -> str:
        url = urljoin(self.credentials.api_host + "/", endpoint_path.lstrip("/"))
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise PoyntConfigurationError("Poynt API requests must use HTTPS.")
        expected_host = urlparse(self.credentials.api_host).netloc
        if parsed.netloc != expected_host:
            # Defence in depth: a path must never be able to retarget the host.
            raise PoyntConfigurationError("Refusing to send a payment request to an unexpected host.")
        return url

    def request(
        self,
        *,
        method: str,
        endpoint_path: str,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
        idempotent: bool = False,
        _is_retry: bool = False,
    ) -> dict[str, Any]:
        """
        Make an authenticated Poynt API call and return the decoded JSON body.

        `request_id` is sent as Poynt-Request-Id. Poynt uses it for idempotency:
        replaying a request with the same id returns the original outcome rather
        than performing the operation twice. Always pass a stable id for charges.

        Raises PoyntTimeoutError when the outcome is UNKNOWN — callers must
        reconcile rather than retry.
        """
        creds = self.credentials
        url = self._build_url(endpoint_path)
        token = self.get_access_token(force_refresh=_is_retry)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "api-version": creds.api_version,
            "Poynt-Request-Id": request_id or str(uuid.uuid4()),
        }

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                data=json.dumps(json_body) if json_body is not None else None,
                headers=headers,
                timeout=creds.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise PoyntTimeoutError(
                f"Poynt request timed out after {creds.timeout_seconds}s; outcome unknown."
            ) from exc
        except requests.ConnectionError as exc:
            # A dropped connection is equally ambiguous for a non-idempotent write.
            if idempotent:
                raise PoyntAPIError(f"Could not reach Poynt: {exc}") from exc
            raise PoyntTimeoutError(f"Connection to Poynt failed mid-request; outcome unknown: {exc}") from exc
        except requests.RequestException as exc:
            raise PoyntAPIError(f"Poynt request failed: {exc}") from exc

        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {}

        # An expired/invalidated token is retried exactly once with a fresh token.
        if response.status_code == 401 and not _is_retry:
            logger.info("Poynt returned 401; refreshing access token and retrying once")
            self.clear_cached_token()
            return self.request(
                method=method,
                endpoint_path=endpoint_path,
                json_body=json_body,
                request_id=request_id,
                idempotent=idempotent,
                _is_retry=True,
            )

        if response.status_code >= 400:
            message = (
                payload.get("developerMessage")
                or payload.get("message")
                or payload.get("error_description")
                or payload.get("error")
                or response.reason
                or "unknown error"
            )
            raise PoyntAPIError(
                f"Poynt API error (HTTP {response.status_code}): {message}",
                status_code=response.status_code,
                payload=payload if isinstance(payload, dict) else {},
            )

        return payload if isinstance(payload, dict) else {}
