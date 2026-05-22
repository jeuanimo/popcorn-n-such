from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from cart.models import Cart

from .models import Coupon, CouponDiscountType, CouponRedemption


@dataclass(frozen=True)
class CouponQuote:
    coupon: Coupon
    eligible_subtotal_cents: int
    discount_cents: int


class CouponService:
    @staticmethod
    def normalize_code(code: str) -> str:
        return (code or "").strip().upper()

    @classmethod
    def _is_fundraiser_cart(cls, cart: Cart) -> bool:
        attribution = getattr(cart, "attribution", None)
        if not attribution:
            return False
        if getattr(attribution, "seller_store_id", None):
            return True
        if (getattr(attribution, "fundraiser_campaign", "") or "").strip():
            return True
        return False

    @classmethod
    def get_coupon_or_error(cls, *, code: str) -> Coupon:
        normalized = cls.normalize_code(code)
        if not normalized:
            raise ValidationError("Enter a coupon code.")
        coupon = Coupon.objects.filter(code=normalized).first()
        if not coupon:
            raise ValidationError("Coupon code not recognized.")
        if not coupon.is_active:
            raise ValidationError("This coupon is inactive.")
        if not coupon.is_within_date_range():
            raise ValidationError("This coupon is expired or not yet active.")
        return coupon

    @classmethod
    def quote_discount(cls, *, cart: Cart, user=None) -> CouponQuote | None:
        """
        Returns a discount quote for the cart's stored coupon code.
        Raises ValidationError if a coupon code is present but invalid.
        """
        if not cart.coupon_code:
            return None

        coupon = cls.get_coupon_or_error(code=cart.coupon_code)

        subtotal_cents = int(cart.items_subtotal * 100)
        if subtotal_cents <= 0:
            return CouponQuote(coupon=coupon, eligible_subtotal_cents=0, discount_cents=0)

        if coupon.minimum_cart_subtotal_cents and subtotal_cents < coupon.minimum_cart_subtotal_cents:
            raise ValidationError("Cart subtotal does not meet the minimum required for this coupon.")

        if cls._is_fundraiser_cart(cart) and not coupon.applies_to_fundraiser_orders:
            raise ValidationError("This coupon does not apply to fundraiser orders.")

        # Determine eligible line subtotal based on product/category targeting.
        product_ids = set(coupon.applies_to_products.values_list("id", flat=True))
        category_ids = set(coupon.applies_to_categories.values_list("id", flat=True))

        eligible_subtotal_cents = 0
        for item in cart.items.select_related("sku__product__category"):
            product_id = item.sku.product_id
            category_id = item.sku.product.category_id
            if product_ids or category_ids:
                if product_ids and product_id in product_ids:
                    pass
                elif category_ids and category_id in category_ids:
                    pass
                else:
                    continue
            eligible_subtotal_cents += int(item.sku.retail_price * 100) * item.quantity

        if eligible_subtotal_cents <= 0:
            raise ValidationError("This coupon does not apply to any items in your cart.")

        # Enforce usage limits.
        total_used = coupon.redemptions.count()
        if coupon.usage_limit is not None and total_used >= coupon.usage_limit:
            raise ValidationError("This coupon has reached its usage limit.")

        if user and getattr(user, "is_authenticated", False):
            used_by_customer = coupon.redemptions.filter(customer=user).count()
            if coupon.per_customer_limit is not None and used_by_customer >= coupon.per_customer_limit:
                raise ValidationError("You have reached the usage limit for this coupon.")

        discount_cents = cls._compute_discount_cents(coupon=coupon, eligible_subtotal_cents=eligible_subtotal_cents)
        discount_cents = max(0, min(discount_cents, eligible_subtotal_cents))
        return CouponQuote(coupon=coupon, eligible_subtotal_cents=eligible_subtotal_cents, discount_cents=discount_cents)

    @staticmethod
    def _compute_discount_cents(*, coupon: Coupon, eligible_subtotal_cents: int) -> int:
        if coupon.discount_type == CouponDiscountType.FIXED:
            return int(coupon.amount_off_cents)
        pct = Decimal(str(coupon.percent_off or 0))
        return int((Decimal(eligible_subtotal_cents) * pct / Decimal("100")).quantize(Decimal("1")))

    @classmethod
    def apply_coupon_to_cart(cls, *, cart: Cart, code: str, user=None) -> CouponQuote:
        cart.coupon_code = cls.normalize_code(code)
        cart.save(update_fields=["coupon_code", "updated_at"])
        quote = cls.quote_discount(cart=cart, user=user)
        if not quote:
            raise ValidationError("Coupon could not be applied.")
        return quote

    @classmethod
    def remove_coupon_from_cart(cls, *, cart: Cart) -> None:
        cart.coupon_code = ""
        cart.save(update_fields=["coupon_code", "updated_at"])

    @classmethod
    @transaction.atomic
    def record_redemption_for_order(cls, *, order, user=None, coupon_code: str) -> CouponRedemption | None:
        """
        Called after payment is confirmed. Idempotent per order.
        """
        if not coupon_code:
            return None
        coupon = cls.get_coupon_or_error(code=coupon_code)
        if CouponRedemption.objects.filter(order=order).exists():
            return CouponRedemption.objects.filter(order=order).first()
        redemption = CouponRedemption.objects.create(
            coupon=coupon,
            order=order,
            customer=user if user and getattr(user, "is_authenticated", False) else None,
            discount_cents=int(getattr(order, "discount_cents", 0) or 0),
            metadata={"order_number": order.order_number},
        )
        return redemption

