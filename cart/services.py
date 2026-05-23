from __future__ import annotations

from decimal import Decimal

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .models import Cart, CartAttribution, CartItem, SavedForLaterItem

RECOVERY_TOKEN_SALT = "cart-recovery"
RECOVERY_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 3
CART_ITEM_NOT_FOUND_MSG = "Cart item not found."


class CartService:
    SESSION_CART_ID_KEY = "cart_id"

    @staticmethod
    def _is_authenticated(request) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)

    @staticmethod
    def _ensure_session_key(request) -> str:
        if not request.session.session_key:
            request.session.cycle_key()
            request.session.save()
        return request.session.session_key

    @classmethod
    def get_or_create_cart(cls, request):
        session_key = cls._ensure_session_key(request)

        if cls._is_authenticated(request):
            user_cart, _ = Cart.objects.get_or_create(user=request.user, is_active=True, defaults={"session_key": session_key})
            guest_cart = Cart.objects.filter(
                user__isnull=True,
                session_key=session_key,
                is_active=True,
            ).exclude(id=user_cart.id).first()
            if guest_cart:
                cls.merge_carts(user_cart=user_cart, guest_cart=guest_cart)
            request.session[cls.SESSION_CART_ID_KEY] = user_cart.id
            return user_cart

        cart, _ = Cart.objects.get_or_create(user__isnull=True, session_key=session_key, is_active=True)
        request.session[cls.SESSION_CART_ID_KEY] = cart.id
        return cart

    @staticmethod
    @transaction.atomic
    def merge_carts(*, user_cart: Cart, guest_cart: Cart):
        for item in guest_cart.items.select_related("sku"):
            target_item = CartItem.objects.filter(cart=user_cart, sku=item.sku).first()
            if target_item:
                target_item.quantity += item.quantity
                target_item.save(update_fields=["quantity", "updated_at"])
            else:
                item.cart = user_cart
                item.save(update_fields=["cart", "updated_at"])

        for saved in guest_cart.saved_items.select_related("sku"):
            target_saved = SavedForLaterItem.objects.filter(cart=user_cart, sku=saved.sku).first()
            if target_saved:
                target_saved.quantity += saved.quantity
                target_saved.save(update_fields=["quantity", "updated_at"])
            else:
                saved.cart = user_cart
                saved.save(update_fields=["cart", "updated_at"])

        if hasattr(guest_cart, "attribution") and not hasattr(user_cart, "attribution"):
            guest_cart.attribution.cart = user_cart
            guest_cart.attribution.save(update_fields=["cart", "updated_at"])

        guest_cart.is_active = False
        guest_cart.save(update_fields=["is_active", "updated_at"])

    @staticmethod
    def _validate_cart_owner(request, cart: Cart):
        if CartService._is_authenticated(request):
            if cart.user_id != request.user.id:
                raise PermissionDenied("You do not have access to this cart.")
        elif cart.session_key != request.session.session_key:
            raise PermissionDenied("Invalid session cart access.")

    @classmethod
    @transaction.atomic
    def add_item(cls, *, request, sku, quantity: int = 1):
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        if not sku.is_purchasable:
            raise ValidationError("This SKU is currently unavailable.")
        if quantity > sku.inventory_quantity:
            raise ValidationError(
                f"Only {sku.inventory_quantity} item(s) are available for {sku.size}."
            )

        cart = cls.get_or_create_cart(request)
        cls._validate_cart_owner(request, cart)
        item, created = CartItem.objects.get_or_create(cart=cart, sku=sku, defaults={"quantity": quantity})
        if not created:
            requested_total = item.quantity + quantity
            if requested_total > sku.inventory_quantity:
                raise ValidationError(
                    f"Only {sku.inventory_quantity} item(s) are available for {sku.size}."
                )
            item.quantity = requested_total
            item.save(update_fields=["quantity", "updated_at"])

        return cart

    @classmethod
    @transaction.atomic
    def update_item_quantity(cls, *, request, item_id: int, quantity: int):
        cart = cls.get_or_create_cart(request)
        item = CartItem.objects.filter(id=item_id, cart=cart).select_related("sku").first()
        if not item:
            raise PermissionDenied(CART_ITEM_NOT_FOUND_MSG)
        if quantity < 1:
            item.delete()
            return 0
        if quantity > item.sku.inventory_quantity:
            raise ValidationError(
                f"Only {item.sku.inventory_quantity} item(s) are available for {item.sku.size}."
            )
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])
        return item.quantity

    @classmethod
    @transaction.atomic
    def remove_item(cls, *, request, item_id: int):
        cart = cls.get_or_create_cart(request)
        item = CartItem.objects.filter(id=item_id, cart=cart).first()
        if not item:
            raise PermissionDenied(CART_ITEM_NOT_FOUND_MSG)
        item.delete()
        return cart

    @classmethod
    @transaction.atomic
    def save_for_later(cls, *, request, item_id: int):
        cart = cls.get_or_create_cart(request)
        item = CartItem.objects.filter(id=item_id, cart=cart).select_related("sku").first()
        if not item:
            raise PermissionDenied(CART_ITEM_NOT_FOUND_MSG)

        saved, created = SavedForLaterItem.objects.get_or_create(
            cart=cart,
            sku=item.sku,
            defaults={"quantity": item.quantity},
        )
        if not created:
            saved.quantity += item.quantity
            saved.save(update_fields=["quantity", "updated_at"])
        item.delete()
        return cart

    @classmethod
    @transaction.atomic
    def move_to_cart(cls, *, request, saved_item_id: int):
        cart = cls.get_or_create_cart(request)
        saved_item = SavedForLaterItem.objects.filter(id=saved_item_id, cart=cart).select_related("sku").first()
        if not saved_item:
            raise PermissionDenied("Saved item not found.")
        if not saved_item.sku.is_purchasable:
            raise ValidationError("This SKU is currently unavailable.")
        if saved_item.quantity > saved_item.sku.inventory_quantity:
            raise ValidationError(
                f"Only {saved_item.sku.inventory_quantity} item(s) are available for {saved_item.sku.size}."
            )

        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            sku=saved_item.sku,
            defaults={"quantity": saved_item.quantity},
        )
        if not created:
            requested_total = cart_item.quantity + saved_item.quantity
            if requested_total > saved_item.sku.inventory_quantity:
                raise ValidationError(
                    f"Only {saved_item.sku.inventory_quantity} item(s) are available for {saved_item.sku.size}."
                )
            cart_item.quantity = requested_total
            cart_item.save(update_fields=["quantity", "updated_at"])
        saved_item.delete()
        return cart

    @classmethod
    def set_attribution(cls, *, request, fundraiser_campaign: str = "", team: str = "", seller: str = "", overwrite: bool = False):
        cart = cls.get_or_create_cart(request)
        attribution, _ = CartAttribution.objects.get_or_create(cart=cart)

        if overwrite or not any([attribution.fundraiser_campaign, attribution.team, attribution.seller]):
            attribution.fundraiser_campaign = fundraiser_campaign[:120]
            attribution.team = team[:120]
            attribution.seller = seller[:120]
            update_fields = ["fundraiser_campaign", "team", "seller", "updated_at"]
            if overwrite:
                # Manual overwrite should reset secure FK attribution sources as well;
                # otherwise stale share-link/seller-store attribution can still apply.
                attribution.campaign = None
                attribution.team_ref = None
                attribution.seller_store = None
                attribution.share_link = None
                update_fields.extend(["campaign", "team_ref", "seller_store", "share_link"])
            attribution.save(update_fields=update_fields)

        return attribution

    @classmethod
    def set_seller_store_attribution(cls, *, request, store) -> None:
        """
        Securely attribute the current cart to a seller store.
        Attribution is set server-side from the store object — never from
        user-supplied URL parameters — preventing spoofing.
        Silently overwrites any previous seller store attribution.
        """
        cart = cls.get_or_create_cart(request)
        attribution, _ = CartAttribution.objects.get_or_create(cart=cart)
        attribution.seller_store = store
        attribution.campaign = store.campaign
        attribution.team_ref = store.team
        attribution.seller = store.display_name[:120]
        if store.campaign:
            attribution.fundraiser_campaign = store.campaign.campaign_name[:120]
        if store.team:
            attribution.team = store.team.name[:120]
        attribution.save(update_fields=["seller_store", "campaign", "team_ref", "seller", "fundraiser_campaign", "team", "updated_at"])

    @classmethod
    def set_campaign_attribution(cls, *, request, campaign) -> None:
        cart = cls.get_or_create_cart(request)
        attribution, _ = CartAttribution.objects.get_or_create(cart=cart)
        attribution.campaign = campaign
        attribution.team_ref = None
        attribution.seller_store = None
        attribution.fundraiser_campaign = campaign.campaign_name[:120]
        attribution.team = ""
        attribution.seller = ""
        attribution.save(update_fields=["campaign", "team_ref", "seller_store", "fundraiser_campaign", "team", "seller", "updated_at"])

    @classmethod
    def set_team_attribution(cls, *, request, team) -> None:
        cart = cls.get_or_create_cart(request)
        attribution, _ = CartAttribution.objects.get_or_create(cart=cart)
        attribution.campaign = team.campaign
        attribution.team_ref = team
        attribution.seller_store = None
        if team.campaign:
            attribution.fundraiser_campaign = team.campaign.campaign_name[:120]
        attribution.team = team.name[:120]
        attribution.seller = ""
        attribution.save(update_fields=["campaign", "team_ref", "seller_store", "fundraiser_campaign", "team", "seller", "updated_at"])

    @classmethod
    def set_share_link(cls, *, request, share_link) -> None:
        cart = cls.get_or_create_cart(request)
        attribution, _ = CartAttribution.objects.get_or_create(cart=cart)
        attribution.share_link = share_link
        attribution.save(update_fields=["share_link", "updated_at"])

    @classmethod
    def apply_attribution_from_request(cls, request):
        # Attribution from arbitrary request params is intentionally disabled.
        # Fundraiser attribution must come from secure server-side flows
        # (seller store views and share-link redirects), not main-store query params.
        return None

    @classmethod
    def summary(cls, *, cart: Cart) -> dict:
        subtotal = Decimal("0.00")
        for item in cart.items.select_related("sku"):
            subtotal += item.sku.retail_price * item.quantity

        estimated_tax = Decimal("0.00")
        estimated_shipping = Decimal("0.00")
        discount = Decimal("0.00")
        coupon_error = ""
        coupon = None
        if cart.coupon_code:
            try:
                from coupons.services import CouponService

                quote = CouponService.quote_discount(cart=cart, user=cart.user)
                if quote:
                    discount = Decimal(quote.discount_cents) / Decimal("100")
                    coupon = quote.coupon
            except Exception as exc:
                coupon_error = str(exc)
                discount = Decimal("0.00")

        destination_state = ""
        destination_postal_code = ""
        destination_country = "US"
        if cart.user_id:
            try:
                default_addr = cart.user.saved_addresses.filter(is_default=True).first()
                if default_addr:
                    destination_state = default_addr.state
                    destination_postal_code = default_addr.postal_code
                    destination_country = default_addr.country
            except Exception:
                pass

        if destination_state:
            try:
                from orders.services import CheckoutService

                checkout_summary = CheckoutService().calculate_totals(
                    cart,
                    destination_state,
                    postal_code=destination_postal_code,
                    country=destination_country,
                )
                estimated_tax = Decimal(checkout_summary.tax_cents) / Decimal("100")
                estimated_shipping = Decimal(checkout_summary.shipping_cents) / Decimal("100")
                # Keep coupon details from current cart quote display, but use calculated totals.
                total = Decimal(checkout_summary.total_cents) / Decimal("100")
            except Exception:
                total = max(Decimal("0.00"), subtotal - discount) + estimated_tax + estimated_shipping
        else:
            total = max(Decimal("0.00"), subtotal - discount)


        return {
            "subtotal": subtotal,
            "discount": discount,
            "estimated_tax": estimated_tax,
            "estimated_shipping": estimated_shipping,
            "total": total,
            "coupon": coupon,
            "coupon_error": coupon_error,
        }

    @staticmethod
    def generate_recovery_token(*, cart: Cart) -> str:
        payload = {
            "cart_id": cart.id,
            "user_id": cart.user_id,
            "session_key": cart.session_key,
        }
        return signing.dumps(payload, salt=RECOVERY_TOKEN_SALT)

    @classmethod
    def recover_from_token(cls, *, request, token: str, max_age: int = RECOVERY_TOKEN_MAX_AGE_SECONDS) -> Cart:
        try:
            payload = signing.loads(token, salt=RECOVERY_TOKEN_SALT, max_age=max_age)
        except signing.BadSignature as exc:
            raise ValidationError("Invalid or expired recovery link.") from exc

        cart = Cart.objects.filter(id=payload.get("cart_id"), is_active=True).first()
        if not cart:
            raise ValidationError("Cart not found.")

        if cls._is_authenticated(request):
            if cart.user_id and cart.user_id != request.user.id:
                raise PermissionDenied("This cart recovery link is not valid for your account.")
            cart.user = request.user
            cart.save(update_fields=["user", "updated_at"])
        else:
            session_key = cls._ensure_session_key(request)
            cart.user = None
            cart.session_key = session_key
            cart.save(update_fields=["user", "session_key", "updated_at"])

        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Cart recovered from signed link",
            actor=request.user if cls._is_authenticated(request) else None,
            request=request,
            target=cart,
        )
        return cart
