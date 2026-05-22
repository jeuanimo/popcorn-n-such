from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from orders.models import Order, OrderStatus, PaymentStatus
from security_audit.models import AuditAction
from security_audit.models import AuditLog
from shipping.carriers.base import LabelResult, RateQuote, ValidationResult
from shipping.carriers.base import PackageInput
from shipping.services import AddressData, ShippingService

User = get_user_model()


class _DummyCarrier:
    slug = "dummy"

    def validate_address(self, address, *, actor=None, request=None):  # noqa: ANN001
        return ValidationResult(provider="dummy", is_valid=True, is_corrected=False, raw={"ok": True})

    def get_rates(self, rate_request, *, actor=None, django_request=None):  # noqa: ANN001
        return [
            RateQuote(
                provider="dummy",
                carrier="DummyCarrier",
                service_name="Ground",
                service_code="GROUND",
                rate_cents=500,
                provider_rate_id="rate-1",
                raw={"stub": True},
            )
        ]

    def create_label(self, label_request, *, actor=None, django_request=None):  # noqa: ANN001
        return LabelResult(
            provider="dummy",
            carrier="DummyCarrier",
            service_name="Ground",
            tracking_number="TRACK123",
            tracking_url="http://track",
            label_format=label_request.label_format,
            label_url="http://label",
            rate_cents=500,
            provider_label_id="lbl-1",
            raw={"stub": True},
        )

    def void_label(self, provider_label_id: str, *, actor=None, django_request=None):  # noqa: ANN001
        return {"status": "voided", "provider_label_id": provider_label_id}


class ShippingServiceTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff_ship", password="pw", is_staff=True)
        self.customer = User.objects.create_user(username="cust_ship", password="pw")
        self.order = Order.objects.create(
            customer=self.customer,
            shipping_recipient_name="X",
            shipping_address_line_1="1 Main",
            shipping_city="Chicago",
            shipping_state="IL",
            shipping_postal_code="60601",
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
            subtotal_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            total_cents=1000,
        )

    @patch("shipping.services.get_shipping_carrier", return_value=_DummyCarrier())
    def test_get_rates_uses_carrier_and_persists(self, _mock_carrier):
        svc = ShippingService(provider="dummy")
        package = PackageInput(weight_oz=10, length_in=4, width_in=4, height_in=4)
        rates = svc.get_rates(self.order, from_postal_code="60601", package=package, actor=self.staff)
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].rate_cents, 500)

    @patch("shipping.services.get_shipping_carrier", return_value=_DummyCarrier())
    def test_create_label_permission_and_audit_log(self, _mock_carrier):
        svc = ShippingService(provider="dummy")

        # Create a rate row first
        from shipping.models import ShippingRate
        from shipping.carriers.base import PackageInput

        rate = ShippingRate.objects.create(
            order=self.order,
            provider="dummy",
            carrier="DummyCarrier",
            service_name="Ground",
            service_code="GROUND",
            rate_cents=500,
            currency="USD",
            provider_rate_id="rate-1",
            raw_response={"stub": True},
        )
        package = PackageInput(weight_oz=10, length_in=4, width_in=4, height_in=4)
        from_addr = AddressData(recipient_name="Warehouse", address_line_1="1 W", city="X", state="IL", postal_code="60601")

        with self.assertRaises(PermissionDenied):
            svc.create_label(self.order, rate, from_addr, package, actor=self.customer)

        label = svc.create_label(self.order, rate, from_addr, package, actor=self.staff)
        self.assertEqual(label.tracking_number, "TRACK123")
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.LABEL_CREATED, metadata__label_id=label.id).exists())
