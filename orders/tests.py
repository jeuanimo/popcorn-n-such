from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cart.models import Cart, CartItem
from orders.models import OrderStatus, PaymentStatus
from products.models import Product, ProductCategory, SKU

from .services import AddressData, CheckoutInput, CheckoutService
from accounts.models import Role, UserRole
from orders.models import Order

User = get_user_model()


@dataclass(frozen=True)
class _TaxResult:
    tax_cents: int
    raw: dict


class _FakeTaxProvider:
    def calculate_tax(self, req):  # noqa: ANN001
        # 5% tax rate for predictable assertions
        return _TaxResult(tax_cents=int(req.taxable_subtotal_cents * 0.05), raw={"stub": True})


class CheckoutServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer", password="pw", email="b@example.com")
        cat = ProductCategory.objects.create(key="pop", name="Popcorn")
        self.product = Product.objects.create(
            name="Butter Pop",
            slug="butter-pop",
            category=cat,
            flavor="butter",
            fundraiser_eligible=True,
            standalone_store_eligible=True,
            is_active=True,
        )
        self.sku = SKU.objects.create(
            sku_code="SKU-1",
            product=self.product,
            size="Small",
            retail_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            inventory_quantity=10,
            is_active=True,
        )
        self.cart = Cart.objects.create(user=self.user, session_key="s", is_active=True)
        CartItem.objects.create(cart=self.cart, sku=self.sku, quantity=2)  # $20

    @patch("orders.services.get_tax_provider", return_value=_FakeTaxProvider())
    def test_checkout_totals_recalculated_server_side(self, _mock_tp):
        service = CheckoutService()
        summary = service.calculate_totals(self.cart, "IL")
        self.assertEqual(summary.subtotal_cents, 2000)
        # 5% of 2000 = 100
        self.assertEqual(summary.tax_cents, 100)
        self.assertEqual(summary.total_cents, 2100)

        # Change SKU price; totals should reflect new server-side price.
        self.sku.retail_price = Decimal("12.00")
        self.sku.save(update_fields=["retail_price", "updated_at"])
        summary2 = service.calculate_totals(self.cart, "IL")
        self.assertEqual(summary2.subtotal_cents, 2400)
        self.assertEqual(summary2.tax_cents, 120)
        self.assertEqual(summary2.total_cents, 2520)

    @patch("orders.services.get_tax_provider", return_value=_FakeTaxProvider())
    def test_inventory_decrements_only_during_confirmed_order(self, _mock_tp):
        service = CheckoutService()
        summary = service.calculate_totals(self.cart, "IL")

        shipping = AddressData(
            recipient_name="Test",
            phone="",
            address_line_1="1 Main",
            address_line_2="",
            city="Chicago",
            state="IL",
            postal_code="60601",
            country="US",
        )
        checkout_input = CheckoutInput(cart=self.cart, shipping=shipping, guest_email="", guest_phone="", user=self.user)
        order = service.create_confirmed_order(
            summary=summary,
            checkout_input=checkout_input,
            payment_result={"provider": "godaddy", "status": "captured", "provider_ref": "stub"},
            actor=self.user,
        )
        self.sku.refresh_from_db()
        self.assertEqual(self.sku.inventory_quantity, 8)  # 10 - 2
        self.assertEqual(order.status, OrderStatus.PAID)
        self.assertEqual(order.payment_status, PaymentStatus.CAPTURED)
        self.assertFalse(Cart.objects.get(id=self.cart.id).is_active)


class OrderAccessControlTests(TestCase):
    def setUp(self):
        self.customer_role, _ = Role.objects.get_or_create(key=UserRole.CUSTOMER)
        self.user1 = User.objects.create_user(username="u1", password="pw1", email="u1@example.com")
        self.user1.roles.add(self.customer_role)
        self.user2 = User.objects.create_user(username="u2", password="pw2", email="u2@example.com")
        self.user2.roles.add(self.customer_role)

        self.order_user1 = Order.objects.create(
            customer=self.user1,
            subtotal_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            discount_cents=0,
            total_cents=1000,
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
        )
        self.order_user2 = Order.objects.create(
            customer=self.user2,
            subtotal_cents=2000,
            tax_cents=0,
            shipping_cents=0,
            discount_cents=0,
            total_cents=2000,
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
        )

    def test_customer_order_list_only_shows_own_orders(self):
        self.client.login(username="u1", password="pw1")
        resp = self.client.get(reverse("orders:my-orders"))
        self.assertEqual(resp.status_code, 200)
        orders = list(resp.context["object_list"])
        self.assertEqual([o.id for o in orders], [self.order_user1.id])

    def test_customer_cannot_view_other_customers_order_detail(self):
        self.client.login(username="u1", password="pw1")
        resp = self.client.get(reverse("orders:order-detail", args=[self.order_user2.id]))
        self.assertEqual(resp.status_code, 404)
