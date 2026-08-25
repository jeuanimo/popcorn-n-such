"""
Tests for the GoDaddy Payments / Poynt Collect integration.

No test in this module performs a real charge: every outbound HTTP call is
mocked. The suite covers the security boundary (server-authoritative pricing,
no card data reaching Django), the duplicate-charge guard, and the ambiguous
outcome handling that prevents double-charging after a network failure.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from cart.models import Cart, CartItem
from orders.models import Order, OrderStatus
from orders.models import PaymentStatus as OrderPaymentStatus
from payments.checkout import (
    PAYMENT_INTENT_SESSION_KEY,
    PaymentAlreadyInFlight,
    charge_checkout,
    issue_payment_intent_key,
)
from payments.gateways.godaddy import GoDaddyPaymentGateway
from payments.gateways.poynt_auth import (
    PoyntAPIError,
    PoyntAuthError,
    PoyntClient,
    PoyntConfigurationError,
    PoyntTimeoutError,
)
from payments.models import PaymentProvider, PaymentStatus, PaymentTransaction
from products.models import Product, ProductCategory, SKU

User = get_user_model()
TEST_PASSWORD = "test-secret-poynt-9271"

# Generated once per test session; never a real credential.
_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PRIVATE_KEY_PEM = _TEST_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

POYNT_SETTINGS = dict(
    GODADDY_POYNT_APPLICATION_ID="urn:aid:test-application",
    GODADDY_POYNT_BUSINESS_ID="test-business-id",
    GODADDY_POYNT_STORE_ID="test-store-id",
    GODADDY_POYNT_PRIVATE_KEY=TEST_PRIVATE_KEY_PEM,
    GODADDY_POYNT_PRIVATE_KEY_PATH="",
    GODADDY_POYNT_API_HOST="https://services-ote.poynt.net",
    GODADDY_COLLECT_ENABLED=True,
    GODADDY_COLLECT_SDK_URL="https://collect.commerce.ote-godaddy.com/sdk.js",
    GODADDY_COLLECT_BUSINESS_ID="test-business-id",
    GODADDY_COLLECT_APPLICATION_ID="urn:aid:test-application",
    ALLOW_STUB_CHECKOUT_PAYMENT=False,
    PAYMENTS_PROVIDER="godaddy",
)


def approved_charge_response(transaction_id: str = "txn-approved-1") -> dict:
    return {
        "id": transaction_id,
        "status": "CAPTURED",
        "action": "SALE",
        "amounts": {"transactionAmount": 1999, "currency": "USD"},
        "processorResponse": {"status": "Successful", "statusCode": "1"},
    }


def declined_charge_response() -> dict:
    return {
        "id": "txn-declined-1",
        "status": "DECLINED",
        "processorResponse": {"status": "Declined", "statusCode": "05"},
    }


def tokenize_response(token: str = "payment-token-jwt") -> dict:
    return {
        "paymentToken": token,
        "status": "AUTHORIZED",
        "card": {"type": "VISA", "numberLast4": "4242", "status": "ACTIVE"},
        "avsResponse": {"addressResult": "MATCH", "postalCodeResult": "MATCH"},
        "cvvResponse": "MATCH",
    }


class PoyntTestMixin:
    """Shared fixture building: a product, a cart and a signed-in customer."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = User.objects.create_user(
            username="buyer", password=TEST_PASSWORD, email="buyer@example.com"
        )
        category = ProductCategory.objects.create(key="pop", name="Popcorn")
        self.product = Product.objects.create(
            name="Kettle Corn", slug="kettle-corn", category=category, flavor="kettle", is_active=True
        )
        self.sku = SKU.objects.create(
            sku_code="KC-1",
            product=self.product,
            size="small",
            retail_price=Decimal("19.99"),
            cost_price=Decimal("6.00"),
            inventory_quantity=50,
            is_active=True,
        )
        self.cart = Cart.objects.create(user=self.user, is_active=True)
        CartItem.objects.create(cart=self.cart, sku=self.sku, quantity=1)

    def make_order(self, **kwargs) -> Order:
        defaults = dict(
            customer=self.user,
            subtotal_cents=1999,
            tax_cents=0,
            shipping_cents=0,
            discount_cents=0,
            total_cents=1999,
            status=OrderStatus.PENDING_PAYMENT,
            payment_status=OrderPaymentStatus.PENDING,
        )
        defaults.update(kwargs)
        return Order.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Authentication (Phase 5)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class PoyntAuthenticationTests(PoyntTestMixin, TestCase):
    def test_assertion_carries_the_documented_claims(self):
        import jwt

        client = PoyntClient()
        assertion = client._build_assertion()
        public_key = _TEST_KEY.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        claims = jwt.decode(
            assertion, public_key, algorithms=["RS256"], audience="https://services-ote.poynt.net"
        )
        self.assertEqual(claims["iss"], "urn:aid:test-application")
        self.assertEqual(claims["sub"], "urn:aid:test-application")
        self.assertEqual(claims["aud"], "https://services-ote.poynt.net")
        self.assertIn("jti", claims)
        self.assertGreater(claims["exp"], claims["iat"])

    @patch("payments.gateways.poynt_auth.requests.post")
    def test_token_is_requested_with_camelcase_grant_type(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "accessToken": "access-token-1", "expiresIn": 86400, "tokenType": "BEARER"
        }
        token = PoyntClient().get_access_token()

        self.assertEqual(token, "access-token-1")
        _, call_kwargs = mock_post.call_args
        self.assertIn("grantType=urn", call_kwargs["data"])
        self.assertEqual(call_kwargs["headers"]["api-version"], "1.2")
        self.assertIn("Poynt-Request-Id", call_kwargs["headers"])

    @patch("payments.gateways.poynt_auth.requests.post")
    def test_access_token_is_cached_between_calls(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"accessToken": "cached-token", "expiresIn": 86400}

        client = PoyntClient()
        client.get_access_token()
        client.get_access_token()
        client.get_access_token()

        self.assertEqual(mock_post.call_count, 1, "token should be minted once and cached")

    @patch("payments.gateways.poynt_auth.requests.post")
    def test_rejected_credentials_raise_auth_error_without_leaking_key(self, mock_post):
        mock_post.return_value.status_code = 401
        mock_post.return_value.json.return_value = {"error": "invalid_client"}

        with self.assertRaises(PoyntAuthError) as ctx:
            PoyntClient().get_access_token()
        self.assertNotIn("PRIVATE KEY", str(ctx.exception))
        self.assertNotIn(TEST_PRIVATE_KEY_PEM[:40], str(ctx.exception))

    @override_settings(GODADDY_POYNT_PRIVATE_KEY="", GODADDY_POYNT_PRIVATE_KEY_PATH="")
    def test_missing_private_key_is_a_configuration_error(self):
        with self.assertRaises(PoyntConfigurationError):
            PoyntClient()._build_assertion()

    def test_requests_cannot_be_retargeted_to_another_host(self):
        with self.assertRaises(PoyntConfigurationError):
            PoyntClient()._build_url("https://attacker.example.com/businesses/x/charge")


# ---------------------------------------------------------------------------
# Charging (Phases 9, 11)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class ChargeFlowTests(PoyntTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(PoyntClient, "get_access_token", return_value="test-access-token")
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch.object(PoyntClient, "request")
    def test_successful_charge_follows_nonce_then_token_then_charge(self, mock_request):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]

        outcome = charge_checkout(
            nonce="nonce-abc", amount_cents=1999, idempotency_key=uuid.uuid4().hex
        )

        self.assertTrue(outcome.succeeded)
        tx = outcome.transaction_obj
        self.assertEqual(tx.status, PaymentStatus.CONFIRMED)
        self.assertEqual(tx.provider_transaction_id, "txn-approved-1")
        self.assertEqual(tx.card_brand, "VISA")
        self.assertEqual(tx.card_last4, "4242")
        self.assertIsNotNone(tx.confirmed_at)

        # Two calls: tokenize, then charge — the documented sequence.
        self.assertEqual(mock_request.call_count, 2)
        tokenize_call, charge_call = mock_request.call_args_list
        self.assertIn("/cards/tokenize", tokenize_call.kwargs["endpoint_path"])
        self.assertEqual(tokenize_call.kwargs["json_body"], {"nonce": "nonce-abc"})
        self.assertIn("/cards/tokenize/charge", charge_call.kwargs["endpoint_path"])
        self.assertEqual(charge_call.kwargs["json_body"]["action"], "SALE")
        self.assertEqual(charge_call.kwargs["json_body"]["fundingSource"]["cardToken"], "payment-token-jwt")

    @patch.object(PoyntClient, "request")
    def test_charge_amount_comes_from_the_server_not_the_caller_hint(self, mock_request):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]

        charge_checkout(nonce="n", amount_cents=4200, idempotency_key=uuid.uuid4().hex)

        charge_body = mock_request.call_args_list[1].kwargs["json_body"]
        self.assertEqual(charge_body["amounts"]["transactionAmount"], 4200)
        self.assertEqual(charge_body["amounts"]["orderAmount"], 4200)
        self.assertEqual(charge_body["amounts"]["currency"], "USD")

    @patch.object(PoyntClient, "request")
    def test_declined_payment_is_recorded_and_message_is_generic(self, mock_request):
        mock_request.side_effect = [tokenize_response(), declined_charge_response()]

        outcome = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertFalse(outcome.succeeded)
        self.assertFalse(outcome.ambiguous)
        self.assertEqual(outcome.transaction_obj.status, PaymentStatus.FAILED)
        # Customers must not see raw processor text.
        self.assertNotIn("05", outcome.customer_message)
        self.assertIn("not approved", outcome.customer_message)

    @patch.object(PoyntClient, "request")
    def test_invalid_nonce_fails_at_tokenization(self, mock_request):
        mock_request.side_effect = PoyntAPIError("Invalid nonce", status_code=422, payload={})

        outcome = charge_checkout(nonce="bogus", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertFalse(outcome.succeeded)
        self.assertEqual(outcome.transaction_obj.status, PaymentStatus.FAILED)
        self.assertEqual(outcome.transaction_obj.failure_code, "http_422")

    @patch.object(PoyntClient, "request")
    def test_tokenization_without_a_token_does_not_attempt_a_charge(self, mock_request):
        mock_request.return_value = {"status": "FAILED"}  # no paymentToken

        outcome = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertFalse(outcome.succeeded)
        self.assertEqual(mock_request.call_count, 1, "must not charge without a token")

    @patch.object(PoyntClient, "request")
    def test_api_error_marks_failed_without_reconciliation(self, mock_request):
        mock_request.side_effect = PoyntAPIError("Server error", status_code=500, payload={})

        outcome = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertEqual(outcome.transaction_obj.status, PaymentStatus.FAILED)
        self.assertFalse(outcome.transaction_obj.requires_reconciliation)

    @patch.object(PoyntClient, "request")
    def test_timeout_is_ambiguous_and_flagged_for_reconciliation(self, mock_request):
        mock_request.side_effect = PoyntTimeoutError("timed out; outcome unknown")

        outcome = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertFalse(outcome.succeeded)
        self.assertTrue(outcome.ambiguous)
        tx = outcome.transaction_obj
        self.assertEqual(tx.status, PaymentStatus.AMBIGUOUS)
        self.assertTrue(tx.requires_reconciliation)
        self.assertIn("do not retry", outcome.customer_message.lower())

    @patch.object(PoyntClient, "request")
    def test_unexpected_exception_is_treated_as_ambiguous(self, mock_request):
        mock_request.side_effect = RuntimeError("something odd")

        outcome = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex)

        self.assertTrue(outcome.ambiguous)
        self.assertTrue(outcome.transaction_obj.requires_reconciliation)

    def test_non_positive_amount_is_refused(self):
        for amount in (0, -100):
            with self.assertRaises(ValueError):
                charge_checkout(nonce="n", amount_cents=amount, idempotency_key=uuid.uuid4().hex)

    @patch.object(PoyntClient, "request")
    def test_authorize_action_is_not_treated_as_paid(self, mock_request):
        mock_request.side_effect = [
            tokenize_response(),
            {"id": "txn-auth", "status": "AUTHORIZED"},
        ]
        with override_settings(GODADDY_PAYMENTS_CHARGE_ACTION="AUTHORIZE"):
            outcome = charge_checkout(
                nonce="n", amount_cents=1999, idempotency_key=uuid.uuid4().hex
            )
        self.assertFalse(outcome.succeeded, "an authorization is not a completed payment")


# ---------------------------------------------------------------------------
# Duplicate-charge protection (Phase 7 / Rule 7)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class DuplicateChargeProtectionTests(PoyntTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(PoyntClient, "get_access_token", return_value="token")
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch.object(PoyntClient, "request")
    def test_replaying_the_same_key_does_not_charge_twice(self, mock_request):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]
        key = uuid.uuid4().hex

        first = charge_checkout(nonce="n", amount_cents=1999, idempotency_key=key)
        self.assertTrue(first.succeeded)

        with self.assertRaises(PaymentAlreadyInFlight):
            charge_checkout(nonce="n", amount_cents=1999, idempotency_key=key)

        self.assertEqual(mock_request.call_count, 2, "no second charge may be sent")
        self.assertEqual(PaymentTransaction.objects.filter(idempotency_key=key).count(), 1)

    @patch.object(PoyntClient, "request")
    def test_idempotency_key_is_sent_as_poynt_request_id(self, mock_request):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]
        key = "stable-key-123"

        charge_checkout(nonce="n", amount_cents=1999, idempotency_key=key)

        charge_call = mock_request.call_args_list[1]
        self.assertEqual(charge_call.kwargs["request_id"], key)

    @patch.object(PoyntClient, "request")
    def test_an_in_flight_attempt_blocks_a_concurrent_one(self, mock_request):
        key = uuid.uuid4().hex
        PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY,
            status=PaymentStatus.PENDING,
            amount_cents=1999,
            currency="USD",
            idempotency_key=key,
        )
        with self.assertRaises(PaymentAlreadyInFlight):
            charge_checkout(nonce="n", amount_cents=1999, idempotency_key=key)
        mock_request.assert_not_called()

    @patch.object(PoyntClient, "request")
    def test_ambiguous_attempt_is_never_retried_under_the_same_key(self, mock_request):
        key = uuid.uuid4().hex
        PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY,
            status=PaymentStatus.AMBIGUOUS,
            requires_reconciliation=True,
            amount_cents=1999,
            currency="USD",
            idempotency_key=key,
        )
        with self.assertRaises(PaymentAlreadyInFlight) as ctx:
            charge_checkout(nonce="n", amount_cents=1999, idempotency_key=key)
        mock_request.assert_not_called()
        self.assertIn("could not confirm", str(ctx.exception).lower())

    def test_database_refuses_two_confirmed_payments_for_one_order(self):
        from django.db import IntegrityError

        order = self.make_order()
        PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY, status=PaymentStatus.CONFIRMED,
            order=order, amount_cents=1999, currency="USD", idempotency_key=uuid.uuid4().hex,
        )
        with self.assertRaises(IntegrityError):
            PaymentTransaction.objects.create(
                provider=PaymentProvider.GODADDY, status=PaymentStatus.CONFIRMED,
                order=order, amount_cents=1999, currency="USD", idempotency_key=uuid.uuid4().hex,
            )

    def test_intent_key_is_stable_across_page_reloads(self):
        session = {}
        first = issue_payment_intent_key(session)
        second = issue_payment_intent_key(session)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# Reconciliation (Phase 11)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class ReconciliationTests(PoyntTestMixin, TestCase):
    def _ambiguous(self, **kwargs) -> PaymentTransaction:
        defaults = dict(
            provider=PaymentProvider.GODADDY,
            status=PaymentStatus.AMBIGUOUS,
            requires_reconciliation=True,
            amount_cents=1999,
            currency="USD",
            idempotency_key=uuid.uuid4().hex,
        )
        defaults.update(kwargs)
        return PaymentTransaction.objects.create(**defaults)

    @patch.object(GoDaddyPaymentGateway, "get_transaction")
    def test_a_charge_that_did_land_is_marked_confirmed(self, mock_get):
        from payments.reconciliation import reconcile_transaction

        mock_get.return_value = {"id": "txn-found", "status": "CAPTURED"}
        tx = self._ambiguous(provider_transaction_id="txn-found")

        reconcile_transaction(tx)
        tx.refresh_from_db()

        self.assertEqual(tx.status, PaymentStatus.CONFIRMED)
        self.assertFalse(tx.requires_reconciliation)
        self.assertIsNotNone(tx.reconciled_at)

    @patch.object(GoDaddyPaymentGateway, "get_transaction")
    def test_a_charge_that_was_declined_is_marked_failed(self, mock_get):
        from payments.reconciliation import reconcile_transaction

        mock_get.return_value = {"id": "txn-x", "status": "DECLINED"}
        tx = self._ambiguous(provider_transaction_id="txn-x")

        reconcile_transaction(tx)
        tx.refresh_from_db()

        self.assertEqual(tx.status, PaymentStatus.FAILED)
        self.assertFalse(tx.requires_reconciliation)

    @patch.object(GoDaddyPaymentGateway, "get_transaction")
    def test_unresolved_lookup_keeps_the_attempt_ambiguous(self, mock_get):
        from payments.reconciliation import reconcile_transaction

        mock_get.side_effect = PoyntAPIError("gateway down", status_code=503)
        tx = self._ambiguous(provider_transaction_id="txn-y")

        reconcile_transaction(tx)
        tx.refresh_from_db()

        self.assertEqual(tx.status, PaymentStatus.AMBIGUOUS)
        self.assertTrue(tx.requires_reconciliation)
        self.assertEqual(tx.reconciliation_attempts, 1)

    @patch.object(GoDaddyPaymentGateway, "find_transactions")
    def test_search_matches_on_the_idempotency_key(self, mock_find):
        from payments.reconciliation import reconcile_transaction

        tx = self._ambiguous()
        mock_find.return_value = {
            "transactions": [
                {"id": "other", "requestId": "unrelated", "status": "CAPTURED"},
                {"id": "ours", "requestId": tx.idempotency_key, "status": "CAPTURED"},
            ]
        }

        reconcile_transaction(tx)
        tx.refresh_from_db()

        self.assertEqual(tx.status, PaymentStatus.CONFIRMED)
        self.assertEqual(tx.provider_transaction_id, "ours")

    @patch.object(GoDaddyPaymentGateway, "get_transaction")
    def test_reconciliation_never_sends_a_charge(self, mock_get):
        from payments.reconciliation import reconcile_pending

        mock_get.return_value = {"id": "t", "status": "CAPTURED"}
        self._ambiguous(provider_transaction_id="t")

        with patch.object(GoDaddyPaymentGateway, "charge_nonce") as mock_charge:
            reconcile_pending()
            mock_charge.assert_not_called()


# ---------------------------------------------------------------------------
# Checkout endpoint (Phases 6-8)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class CheckoutEndpointTests(PoyntTestMixin, TestCase):
    def server_total_cents(self) -> int:
        """The authoritative total, as the server itself computes it."""
        from orders.services import CheckoutService

        summary = CheckoutService().calculate_totals(
            self.cart, "IL", postal_code="62701", country="US"
        )
        return summary.total_cents

    def _prime_session(self):
        session = self.client.session
        session["checkout_data"] = {
            "guest_email": "",
            "guest_phone": "",
            "recipient_name": "Test Buyer",
            "shipping_phone": "5551234567",
            "address_line_1": "1 Main St",
            "address_line_2": "",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62701",
            "country": "US",
            "cart_id": self.cart.pk,
        }
        session["checkout_summary"] = {
            "subtotal_cents": 1999, "tax_cents": 0, "shipping_cents": 0,
            "discount_cents": 0, "total_cents": 1999,
        }
        session["selected_payment_method"] = "godaddy"
        session.save()
        return session

    def test_review_page_issues_an_intent_key(self):
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()

        response = self.client.get(reverse("orders:checkout-review"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(PAYMENT_INTENT_SESSION_KEY, self.client.session)
        self.assertContains(response, "payment_intent_key")

    def test_review_page_never_exposes_the_private_key(self):
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()

        body = self.client.get(reverse("orders:checkout-review")).content.decode()

        self.assertNotIn("PRIVATE KEY", body)
        self.assertNotIn(TEST_PRIVATE_KEY_PEM[:50], body)
        # No fragment of the key, however it might be chunked into the page.
        for chunk in TEST_PRIVATE_KEY_PEM.split("\n"):
            if len(chunk) > 20:
                self.assertNotIn(chunk, body)
        # The Business ID is safe to publish; escapejs renders "-" as \u002D.
        from django.utils.html import escapejs

        self.assertIn(escapejs("test-business-id"), body)

    @patch("payments.checkout.charge_checkout")
    def test_missing_nonce_is_rejected_before_any_charge(self, mock_charge):
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))

        response = self.client.post(
            reverse("orders:checkout-review"),
            {"payment_method": "godaddy", "poynt_nonce": ""},
        )

        mock_charge.assert_not_called()
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(response.status_code, 302)

    def test_post_without_csrf_token_is_rejected(self):
        from django.test import Client

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="buyer", password=TEST_PASSWORD)

        response = csrf_client.post(
            reverse("orders:checkout-review"),
            {"payment_method": "godaddy", "poynt_nonce": "n"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Order.objects.count(), 0)

    @patch.object(PoyntClient, "get_access_token", return_value="token")
    @patch.object(PoyntClient, "request")
    def test_browser_supplied_amount_is_ignored(self, mock_request, _token):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))

        # Attacker submits a one-cent total alongside the nonce.
        self.client.post(
            reverse("orders:checkout-review"),
            {
                "payment_method": "godaddy",
                "poynt_nonce": "nonce-abc",
                "total_cents": "1",
                "amount": "0.01",
                "amount_cents": "1",
            },
        )

        charge_body = mock_request.call_args_list[1].kwargs["json_body"]
        charged = charge_body["amounts"]["transactionAmount"]
        self.assertNotIn(charged, (1, 0), "the posted amount must never be charged")
        self.assertEqual(
            charged, self.server_total_cents(),
            "the server total must win over anything posted by the browser",
        )

    @patch.object(PoyntClient, "get_access_token", return_value="token")
    @patch.object(PoyntClient, "request")
    def test_successful_checkout_creates_a_paid_order(self, mock_request, _token):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))

        with patch("orders.tasks.run_post_order_tasks.delay"):
            response = self.client.post(
                reverse("orders:checkout-review"),
                {"payment_method": "godaddy", "poynt_nonce": "nonce-abc"},
            )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        # Recalculated server-side: subtotal + shipping + tax, not the session value.
        self.assertEqual(order.total_cents, self.server_total_cents())
        tx = PaymentTransaction.objects.get()
        self.assertEqual(tx.order_id, order.id)
        self.assertTrue(tx.is_confirmed)
        # The key is consumed so a later submit starts a fresh attempt.
        self.assertNotIn(PAYMENT_INTENT_SESSION_KEY, self.client.session)

    @patch.object(PoyntClient, "get_access_token", return_value="token")
    @patch.object(PoyntClient, "request")
    def test_double_submit_creates_only_one_order(self, mock_request, _token):
        mock_request.side_effect = [tokenize_response(), approved_charge_response()]
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))
        intent_key = self.client.session[PAYMENT_INTENT_SESSION_KEY]

        with patch("orders.tasks.run_post_order_tasks.delay"):
            self.client.post(
                reverse("orders:checkout-review"),
                {"payment_method": "godaddy", "poynt_nonce": "nonce-abc"},
            )
            # Simulate the customer's browser replaying the POST with the
            # original session key still in place.
            session = self.client.session
            session[PAYMENT_INTENT_SESSION_KEY] = intent_key
            session.save()
            self.client.post(
                reverse("orders:checkout-review"),
                {"payment_method": "godaddy", "poynt_nonce": "nonce-abc"},
            )

        self.assertEqual(Order.objects.count(), 1, "a replayed POST must not create a second order")
        self.assertEqual(
            PaymentTransaction.objects.filter(idempotency_key=intent_key).count(), 1
        )

    @patch.object(PoyntClient, "get_access_token", return_value="token")
    @patch.object(PoyntClient, "request")
    def test_declined_checkout_creates_no_order(self, mock_request, _token):
        mock_request.side_effect = [tokenize_response(), declined_charge_response()]
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))

        self.client.post(
            reverse("orders:checkout-review"),
            {"payment_method": "godaddy", "poynt_nonce": "nonce-abc"},
        )

        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(PaymentTransaction.objects.get().status, PaymentStatus.FAILED)

    @patch.object(PoyntClient, "get_access_token", return_value="token")
    @patch.object(PoyntClient, "request")
    def test_timeout_sends_customer_to_the_pending_page(self, mock_request, _token):
        mock_request.side_effect = PoyntTimeoutError("dropped")
        self.client.login(username="buyer", password=TEST_PASSWORD)
        self._prime_session()
        self.client.get(reverse("orders:checkout-review"))

        response = self.client.post(
            reverse("orders:checkout-review"),
            {"payment_method": "godaddy", "poynt_nonce": "nonce-abc"},
        )

        self.assertRedirects(response, reverse("orders:payment-pending"))
        self.assertEqual(Order.objects.count(), 0)
        self.assertTrue(PaymentTransaction.objects.get().requires_reconciliation)

    def test_pending_page_does_not_offer_a_retry(self):
        response = self.client.get(reverse("orders:payment-pending"))
        body = response.content.decode().lower()
        self.assertIn("do not try to pay again", body)
        self.assertNotIn("try payment again", body)

    def test_checkout_without_session_data_redirects_to_checkout(self):
        self.client.login(username="buyer", password=TEST_PASSWORD)
        response = self.client.get(reverse("orders:checkout-review"))
        self.assertRedirects(response, reverse("orders:checkout"), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Order ownership and access control
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class OrderAccessControlTests(PoyntTestMixin, TestCase):
    def test_a_customer_cannot_view_another_customers_order(self):
        other = User.objects.create_user(
            username="intruder", password=TEST_PASSWORD, email="intruder@example.com"
        )
        order = self.make_order(customer=self.user, status=OrderStatus.PAID)

        self.client.force_login(other)
        response = self.client.get(reverse("orders:order-detail", args=[order.pk]))

        self.assertIn(response.status_code, (403, 404, 302))

    def test_order_detail_requires_authentication(self):
        order = self.make_order()
        response = self.client.get(reverse("orders:order-detail", args=[order.pk]))
        self.assertIn(response.status_code, (302, 403))


# ---------------------------------------------------------------------------
# Data-handling guarantees (Rule 5)
# ---------------------------------------------------------------------------


class SensitiveDataTests(TestCase):
    def test_payment_model_stores_no_card_secrets(self):
        field_names = {f.name.lower() for f in PaymentTransaction._meta.get_fields() if hasattr(f, "name")}
        for forbidden in ("card_number", "pan", "cvv", "cvc", "expiration", "expiry", "exp_month", "exp_year"):
            self.assertNotIn(forbidden, field_names)

    def test_scrubber_redacts_card_like_payload_fields(self):
        from payments.checkout import _scrub

        cleaned = _scrub({
            "id": "txn-1",
            "card": {"number": "4111111111111111", "cvv": "123", "numberLast4": "1111"},
            "nonce": "secret-nonce",
        })
        self.assertEqual(cleaned["card"]["number"], "[redacted]")
        self.assertEqual(cleaned["card"]["cvv"], "[redacted]")
        self.assertEqual(cleaned["nonce"], "[redacted]")
        self.assertEqual(cleaned["card"]["numberLast4"], "1111", "last four is safe to keep")

    def test_log_filter_redacts_secrets(self):
        from payments.log_filters import redact

        self.assertIn("[CARD REDACTED]", redact("card 4111 1111 1111 1111"))
        self.assertIn("[JWT REDACTED]", redact("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhIn0.signature"))
        self.assertIn("[PRIVATE KEY REDACTED]", redact("-----BEGIN RSA PRIVATE KEY-----"))


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class WebhookSignatureTests(TestCase):
    """
    Note: get_runtime_setting() consults os.environ before Django settings, so
    these tests patch the environment as well as the settings — otherwise a
    developer's real .env value would silently win.
    """

    def setUp(self):
        super().setUp()
        cache.clear()

    @override_settings(GODADDY_PAYMENTS_WEBHOOK_SECRET="", PAYMENTS_WEBHOOK_SECRET="")
    @patch.dict("os.environ", {"GODADDY_PAYMENTS_WEBHOOK_SECRET": "", "PAYMENTS_WEBHOOK_SECRET": ""})
    def test_unsigned_webhook_is_rejected_when_no_secret_configured(self):
        gateway = GoDaddyPaymentGateway()
        self.assertFalse(
            gateway.verify_webhook_signature(body=b"{}", headers={}),
            "webhook verification must fail closed",
        )

    @override_settings(GODADDY_PAYMENTS_WEBHOOK_SECRET="shhh")
    @patch.dict("os.environ", {"GODADDY_PAYMENTS_WEBHOOK_SECRET": "shhh"})
    def test_correctly_signed_webhook_is_accepted(self):
        import hashlib
        import hmac

        body = b'{"type":"payment"}'
        signature = hmac.new(b"shhh", body, hashlib.sha256).hexdigest()
        gateway = GoDaddyPaymentGateway()
        self.assertTrue(
            gateway.verify_webhook_signature(body=body, headers={"X-GoDaddy-Signature": signature})
        )

    @override_settings(GODADDY_PAYMENTS_WEBHOOK_SECRET="shhh")
    @patch.dict("os.environ", {"GODADDY_PAYMENTS_WEBHOOK_SECRET": "shhh"})
    def test_tampered_webhook_is_rejected(self):
        gateway = GoDaddyPaymentGateway()
        self.assertFalse(
            gateway.verify_webhook_signature(
                body=b'{"type":"payment"}', headers={"X-GoDaddy-Signature": "deadbeef"}
            )
        )


# ---------------------------------------------------------------------------
# Refunds (Phase 17)
# ---------------------------------------------------------------------------


@override_settings(**POYNT_SETTINGS)
class RefundTests(PoyntTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            username="staffer", password=TEST_PASSWORD, email="staff@example.com", is_staff=True
        )
        self.order = self.make_order(status=OrderStatus.PAID)
        self.payment = PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY,
            status=PaymentStatus.CONFIRMED,
            order=self.order,
            amount_cents=5000,
            currency="USD",
            provider_transaction_id="txn-original",
            idempotency_key=uuid.uuid4().hex,
        )

    @patch.object(GoDaddyPaymentGateway, "refund_transaction")
    def test_staff_can_issue_a_full_refund(self, mock_refund):
        from payments.models import PaymentRefund
        from payments.refunds import issue_refund

        mock_refund.return_value = type(
            "R", (), {"status": "refunded", "provider_refund_id": "refund-1",
                      "raw": {"id": "refund-1", "status": "REFUNDED"},
                      "failure_code": None, "failure_message": None},
        )()

        refund = issue_refund(payment=self.payment, actor=self.staff, reason="customer request")

        self.assertEqual(refund.status, PaymentStatus.REFUNDED)
        self.assertEqual(refund.amount_cents, 5000)
        self.assertEqual(refund.issued_by, self.staff)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.REFUNDED)
        # The original charge record survives.
        self.assertTrue(PaymentTransaction.objects.filter(pk=self.payment.pk).exists())
        self.assertEqual(PaymentRefund.objects.count(), 1)
        # A full refund omits the amounts block.
        self.assertIsNone(mock_refund.call_args.kwargs["amount_cents"])

    @patch.object(GoDaddyPaymentGateway, "refund_transaction")
    def test_partial_refund_leaves_the_payment_confirmed(self, mock_refund):
        from payments.refunds import issue_refund, refundable_amount_cents

        mock_refund.return_value = type(
            "R", (), {"status": "refunded", "provider_refund_id": "refund-2",
                      "raw": {}, "failure_code": None, "failure_message": None},
        )()

        issue_refund(payment=self.payment, actor=self.staff, amount_cents=2000)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CONFIRMED)
        self.assertEqual(refundable_amount_cents(self.payment), 3000)
        self.assertEqual(mock_refund.call_args.kwargs["amount_cents"], 2000)

    def test_non_staff_cannot_issue_a_refund(self):
        from payments.refunds import RefundNotPermitted, issue_refund

        with self.assertRaises(RefundNotPermitted):
            issue_refund(payment=self.payment, actor=self.user)

    def test_anonymous_cannot_issue_a_refund(self):
        from django.contrib.auth.models import AnonymousUser
        from payments.refunds import RefundNotPermitted, issue_refund

        with self.assertRaises(RefundNotPermitted):
            issue_refund(payment=self.payment, actor=AnonymousUser())

    def test_cannot_refund_an_unconfirmed_payment(self):
        from payments.refunds import RefundError, issue_refund

        failed = PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY, status=PaymentStatus.FAILED,
            amount_cents=1000, currency="USD", idempotency_key=uuid.uuid4().hex,
        )
        with self.assertRaises(RefundError):
            issue_refund(payment=failed, actor=self.staff)

    def test_cannot_refund_more_than_was_charged(self):
        from payments.refunds import RefundError, issue_refund

        with self.assertRaises(RefundError) as ctx:
            issue_refund(payment=self.payment, actor=self.staff, amount_cents=9999)
        self.assertIn("exceeds", str(ctx.exception))

    @patch.object(GoDaddyPaymentGateway, "refund_transaction")
    def test_cannot_over_refund_across_several_partial_refunds(self, mock_refund):
        from payments.refunds import RefundError, issue_refund

        mock_refund.return_value = type(
            "R", (), {"status": "refunded", "provider_refund_id": "r", "raw": {},
                      "failure_code": None, "failure_message": None},
        )()

        issue_refund(payment=self.payment, actor=self.staff, amount_cents=3000)
        issue_refund(payment=self.payment, actor=self.staff, amount_cents=2000)

        with self.assertRaises(RefundError):
            issue_refund(payment=self.payment, actor=self.staff, amount_cents=1)

    @patch.object(GoDaddyPaymentGateway, "refund_transaction")
    def test_refund_timeout_does_not_mark_it_refunded(self, mock_refund):
        from payments.models import PaymentRefund
        from payments.refunds import RefundError, issue_refund

        mock_refund.side_effect = PoyntTimeoutError("timed out")

        with self.assertRaises(RefundError) as ctx:
            issue_refund(payment=self.payment, actor=self.staff)

        self.assertIn("do not issue a second refund", str(ctx.exception).lower())
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.CONFIRMED)
        self.assertEqual(PaymentRefund.objects.get().status, PaymentStatus.PENDING)

    @patch.object(GoDaddyPaymentGateway, "refund_transaction")
    def test_refund_uses_the_original_transaction_id(self, mock_refund):
        from payments.refunds import issue_refund

        mock_refund.return_value = type(
            "R", (), {"status": "refunded", "provider_refund_id": "r", "raw": {},
                      "failure_code": None, "failure_message": None},
        )()

        issue_refund(payment=self.payment, actor=self.staff)

        self.assertEqual(
            mock_refund.call_args.kwargs["provider_transaction_id"], "txn-original"
        )
