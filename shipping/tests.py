from django.test import TestCase
from django.urls import reverse

from django.contrib.auth import get_user_model


class PitneyBowesProviderTests(TestCase):
    def test_oauth_token_cached_and_reused(self):
        import os
        from unittest.mock import patch

        from shipping.gateways.pitney_bowes import PitneyBowesProvider

        provider = PitneyBowesProvider()

        token_payload = b'{"access_token":"tkn","token_type":"Bearer","expires_in":3600}'

        def fake_http_request(*, method, url, headers=None, body=None, timeout=20):
            return 200, {"Content-Type": "application/json"}, token_payload

        with (
            patch.dict(os.environ, {"PITNEY_BOWES_API_KEY": "k", "PITNEY_BOWES_API_SECRET": "s"}, clear=False),
            patch.object(PitneyBowesProvider, "_http_request", side_effect=fake_http_request) as mocked,
        ):
            t1 = provider._get_oauth_token(force_refresh=True)
            t2 = provider._get_oauth_token()

        self.assertEqual(t1.access_token, "tkn")
        self.assertEqual(t2.access_token, "tkn")
        # Only one HTTP call should be needed due to cache reuse.
        self.assertEqual(mocked.call_count, 1)


class PitneyBowesProviderRequestTests(TestCase):
    def test_request_json_adds_bearer_header(self):
        from unittest.mock import patch

        from shipping.gateways.pitney_bowes import PitneyBowesProvider

        provider = PitneyBowesProvider()

        captured = {}

        def fake_http_request(*, method, url, headers=None, body=None, timeout=20):
            captured["headers"] = headers or {}
            return 200, {"Content-Type": "application/json"}, b"{}"

        with patch.object(PitneyBowesProvider, "_http_request", side_effect=fake_http_request):
            provider._request_json(method="GET", path="/test", token="abc123", payload=None)

        self.assertIn("Authorization", captured["headers"])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer abc123")


class USPSProviderTests(TestCase):
    def test_usps_oauth_token_cached_and_reused(self):
        import os
        from unittest.mock import patch

        from shipping.gateways.usps import USPSProvider

        provider = USPSProvider()
        token_payload = b'{"access_token":"usps_tkn","token_type":"Bearer","expires_in":3600}'

        def fake_http_request(*, method, url, headers=None, body=None, timeout=20):
            return 200, {"Content-Type": "application/json"}, token_payload

        with (
            patch.dict(os.environ, {"USPS_CLIENT_ID": "cid", "USPS_CLIENT_SECRET": "csec"}, clear=False),
            patch.object(USPSProvider, "_http_request", side_effect=fake_http_request) as mocked,
        ):
            t1 = provider._get_oauth_token(force_refresh=True)
            t2 = provider._get_oauth_token()

        self.assertEqual(t1.access_token, "usps_tkn")
        self.assertEqual(t2.access_token, "usps_tkn")
        self.assertEqual(mocked.call_count, 1)

    def test_usps_request_json_adds_bearer_header(self):
        from unittest.mock import patch

        from shipping.gateways.usps import USPSProvider

        provider = USPSProvider()
        captured = {}

        def fake_http_request(*, method, url, headers=None, body=None, timeout=20):
            captured["headers"] = headers or {}
            return 200, {"Content-Type": "application/json"}, b"{}"

        with patch.object(USPSProvider, "_http_request", side_effect=fake_http_request):
            provider._request_json(method="GET", path="/test", token="tok", payload=None)

        self.assertEqual(captured["headers"]["Authorization"], "Bearer tok")


class ShippingLabelListViewTests(TestCase):
    def setUp(self):
        self.url = reverse("shipping:label-list")

    def test_non_staff_is_redirected_to_admin_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_staff_can_view_labels_page(self):
        user_model = get_user_model()
        staff = user_model.objects.create(
            username="staff_user",
            email="staff@example.com",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shipping Labels")

# Create your tests here.
