from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from cart.models import Cart, CartAttribution, CartItem
from products.models import Product, ProductCategory, SKU

from .models import Coupon, CouponDiscountType, CouponRedemption
from .services import CouponService

User = get_user_model()


class CouponServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer", password="pw", email="b@x.com")
        self.category = ProductCategory.objects.create(key="popcorn", name="Popcorn")
        self.product = Product.objects.create(
            name="Test Pop",
            slug="test-pop",
            category=self.category,
            flavor="butter",
            is_active=True,
        )
        self.sku = SKU.objects.create(
            sku_code="SKU1",
            product=self.product,
            size="small",
            retail_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            inventory_quantity=100,
            is_active=True,
        )
        self.cart = Cart.objects.create(user=self.user, is_active=True, session_key="s")
        CartItem.objects.create(cart=self.cart, sku=self.sku, quantity=2)  # $20

    def test_percent_coupon_applies_and_caps_to_eligible_subtotal(self):
        c = Coupon.objects.create(code="SAVE10", discount_type=CouponDiscountType.PERCENT, percent_off=Decimal("10.00"))
        self.cart.coupon_code = "save10"
        self.cart.save()
        quote = CouponService.quote_discount(cart=self.cart, user=self.user)
        self.assertEqual(quote.discount_cents, 200)  # 10% of $20

    def test_fixed_coupon_cannot_reduce_below_zero(self):
        Coupon.objects.create(code="BIGOFF", discount_type=CouponDiscountType.FIXED, amount_off_cents=999999)
        self.cart.coupon_code = "BIGOFF"
        self.cart.save()
        quote = CouponService.quote_discount(cart=self.cart, user=self.user)
        self.assertEqual(quote.discount_cents, 2000)  # capped to eligible subtotal

    def test_inactive_coupon_rejected(self):
        Coupon.objects.create(code="NOPE", discount_type=CouponDiscountType.FIXED, amount_off_cents=100, is_active=False)
        self.cart.coupon_code = "NOPE"
        self.cart.save()
        with self.assertRaises(ValidationError):
            CouponService.quote_discount(cart=self.cart, user=self.user)

    def test_expired_coupon_rejected(self):
        today = timezone.localdate()
        Coupon.objects.create(
            code="OLD",
            discount_type=CouponDiscountType.FIXED,
            amount_off_cents=100,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=1),
        )
        self.cart.coupon_code = "OLD"
        self.cart.save()
        with self.assertRaises(ValidationError):
            CouponService.quote_discount(cart=self.cart, user=self.user)

    def test_minimum_subtotal_enforced(self):
        Coupon.objects.create(
            code="MIN100",
            discount_type=CouponDiscountType.FIXED,
            amount_off_cents=100,
            minimum_cart_subtotal_cents=10000,
        )
        self.cart.coupon_code = "MIN100"
        self.cart.save()
        with self.assertRaises(ValidationError):
            CouponService.quote_discount(cart=self.cart, user=self.user)

    def test_fundraiser_restriction_enforced(self):
        Coupon.objects.create(code="DIRECTONLY", discount_type=CouponDiscountType.FIXED, amount_off_cents=100, applies_to_fundraiser_orders=False)
        CartAttribution.objects.create(cart=self.cart, fundraiser_campaign="Spring Drive")
        self.cart.coupon_code = "DIRECTONLY"
        self.cart.save()
        with self.assertRaises(ValidationError):
            CouponService.quote_discount(cart=self.cart, user=self.user)

    def test_per_customer_limit_enforced(self):
        coupon = Coupon.objects.create(
            code="ONCE",
            discount_type=CouponDiscountType.FIXED,
            amount_off_cents=100,
            per_customer_limit=1,
        )
        # Fake prior paid redemption
        from orders.models import Order, OrderStatus, PaymentStatus

        order = Order.objects.create(
            customer=self.user,
            subtotal_cents=2000,
            tax_cents=0,
            shipping_cents=0,
            discount_cents=100,
            total_cents=1900,
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
            coupon_code="ONCE",
        )
        CouponRedemption.objects.create(coupon=coupon, order=order, customer=self.user, discount_cents=100)

        self.cart.coupon_code = "ONCE"
        self.cart.save()
        with self.assertRaises(ValidationError):
            CouponService.quote_discount(cart=self.cart, user=self.user)

