"""Pre-flight check for the payments configuration."""

from django.conf import settings
from django.core.management.base import BaseCommand

from payments.gateways.poynt_auth import describe_configuration, is_configured


class Command(BaseCommand):
    help = (
        "Verify the GoDaddy Payments configuration and report anything unsafe "
        "before going live. Makes no API calls unless --live is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--live",
            action="store_true",
            help="Also authenticate against the configured Poynt host.",
        )
        parser.add_argument(
            "--connectivity",
            action="store_true",
            help=(
                "Probe the configured Poynt host without credentials. Confirms "
                "DNS, TLS and that /token accepts our request shape."
            ),
        )

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  PASS  {msg}"))

    def _warn(self, msg):
        self.stdout.write(self.style.WARNING(f"  WARN  {msg}"))

    def _fail(self, msg):
        self.stdout.write(self.style.ERROR(f"  FAIL  {msg}"))

    def handle(self, *args, **options):
        config = describe_configuration()
        failures = 0
        warnings = 0

        self.stdout.write(self.style.MIGRATE_HEADING("\nPayment processor"))
        self.stdout.write(f"  environment : {config['environment']}")
        self.stdout.write(f"  api host    : {config['api_host']}")

        for label, key in (
            ("Application ID", "application_id_set"),
            ("Business ID", "business_id_set"),
            ("Private key", "private_key_set"),
        ):
            if config[key]:
                self._ok(f"{label} is configured")
            else:
                self._fail(f"{label} is NOT configured")
                failures += 1

        if not config["store_id_set"]:
            self._warn("Store ID is not set (optional, but recommended)")
            warnings += 1

        self.stdout.write(self.style.MIGRATE_HEADING("\nSecurity"))

        if settings.DEBUG:
            self._fail("DEBUG is True — must be False in production")
            failures += 1
        else:
            self._ok("DEBUG is False")

        if getattr(settings, "ALLOW_STUB_CHECKOUT_PAYMENT", False):
            self._fail("ALLOW_STUB_CHECKOUT_PAYMENT is enabled — orders can be placed without paying")
            failures += 1
        else:
            self._ok("Stub checkout payment is disabled")

        if config["is_production"] and settings.DEBUG:
            self._fail("Production payment credentials are in use with DEBUG on")
            failures += 1

        for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SECURE_SSL_REDIRECT"):
            if getattr(settings, name, False):
                self._ok(f"{name} is on")
            elif settings.DEBUG:
                self._warn(f"{name} is off (acceptable in local development)")
                warnings += 1
            else:
                self._fail(f"{name} is off")
                failures += 1

        webhook_secret = (
            getattr(settings, "GODADDY_PAYMENTS_WEBHOOK_SECRET", "")
            or getattr(settings, "PAYMENTS_WEBHOOK_SECRET", "")
        )
        if webhook_secret:
            self._ok("Webhook signing secret is configured")
        else:
            self._warn("No webhook secret set — incoming webhooks will be rejected")
            warnings += 1

        if getattr(settings, "CSP_ENFORCE", False):
            self._ok("Content-Security-Policy is enforced")
        else:
            self._warn("CSP is report-only — enforce it once checkout reports no violations")
            warnings += 1

        if "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE:
            self._ok("CSRF middleware is active")
        else:
            self._fail("CSRF middleware is MISSING")
            failures += 1

        if options["connectivity"] or options["live"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\nConnectivity"))
            failures += self._probe(config["api_host"])

        if options["live"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\nLive connection"))
            if not is_configured():
                self._fail("Cannot test: credentials incomplete")
                failures += 1
            else:
                try:
                    from payments.gateways.registry import get_payment_gateway

                    get_payment_gateway("godaddy").test_poynt_connection()
                    self._ok("Authenticated against Poynt and read the business record")
                except Exception as exc:
                    self._fail(f"Live check failed: {type(exc).__name__}: {exc}")
                    failures += 1

        self.stdout.write("")
        if failures:
            self.stdout.write(self.style.ERROR(f"{failures} blocking problem(s), {warnings} warning(s)."))
        elif warnings:
            self.stdout.write(self.style.WARNING(f"No blocking problems, {warnings} warning(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("All checks passed."))

    def _probe(self, api_host: str) -> int:
        """
        Send a deliberately unsigned-by-us assertion to /token.

        A 401 LOGIN_FAILED is the SUCCESS case here: it proves DNS, TLS, the
        endpoint path, our form encoding and our JWT structure are all correct,
        without needing real credentials.
        """
        import socket
        import urllib.parse

        host = urllib.parse.urlparse(api_host).netloc
        try:
            socket.gethostbyname(host)
            self._ok(f"DNS resolves: {host}")
        except OSError as exc:
            self._fail(f"DNS does NOT resolve: {host} ({exc}). Check GODADDY_POYNT_ENV.")
            return 1

        try:
            import uuid

            import requests
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import jwt

            throwaway = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = throwaway.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
            now = int(__import__("time").time())
            assertion = jwt.encode(
                {
                    "iss": "urn:aid:connectivity-probe",
                    "sub": "urn:aid:connectivity-probe",
                    "aud": api_host,
                    "iat": now,
                    "exp": now + 300,
                    "jti": str(uuid.uuid4()),
                },
                pem,
                algorithm="RS256",
            )
            response = requests.post(
                f"{api_host}/token",
                data={
                    "grantType": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                headers={
                    "Accept": "application/json",
                    "api-version": settings.GODADDY_POYNT_API_VERSION,
                    "Poynt-Request-Id": str(uuid.uuid4()),
                },
                timeout=20,
            )
        except Exception as exc:
            self._fail(f"Could not reach {api_host}: {type(exc).__name__}: {exc}")
            return 1

        self._ok(f"TLS connection to {host} succeeded")

        body = {}
        try:
            body = response.json()
        except ValueError:
            pass

        # The probe key is unknown to Poynt, so rejection-by-issuer is expected
        # and proves the service parsed our signed assertion.
        if response.status_code == 401 and "issuer" in str(body.get("developerMessage", "")).lower():
            self._ok("/token parsed our signed assertion (rejected the probe identity, as expected)")
            return 0
        if response.status_code == 401:
            self._ok(f"/token responded 401 as expected ({body.get('code', 'no code')})")
            return 0
        if response.status_code == 200:
            self._warn("/token returned 200 to a throwaway key — unexpected; investigate")
            return 0

        self._fail(
            f"/token returned HTTP {response.status_code}: "
            f"{body.get('developerMessage') or body.get('message') or response.reason}"
        )
        return 1
