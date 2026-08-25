from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cart.models import Cart
from cart.models import CartAttribution
from fulfillment.models import FulfillmentRecord
from fulfillment.services import FulfillmentRequest, FulfillmentService
from fundraisers.models import FundraiserCampaign
from notifications.models import NotificationChannel, NotificationStatus, OrderNotification
from payments.models import PaymentStatus as TxPaymentStatus
from payments.models import PaymentTransaction
from products.models import SKU
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from taxes.providers.base import ShippingAddress, TaxQuoteRequest
from taxes.registry import get_tax_provider
from shipping.carriers.base import AddressInput, PackageInput, RateRequest
from shipping.carriers.registry import get_shipping_carrier

from .models import Order, OrderItem, OrderStatus, PaymentStatus


@dataclass
class AddressData:
    recipient_name: str
    phone: str
    address_line_1: str
    city: str
    state: str
    postal_code: str
    address_line_2: str = ""
    country: str = "US"


@dataclass
class CheckoutInput:
    cart: Cart
    shipping: AddressData
    billing: "AddressData | None" = None  # None means same as shipping
    guest_email: str = ""
    guest_phone: str = ""
    user: object = None


@dataclass
class CheckoutSummary:
    subtotal_cents: int
    tax_cents: int
    shipping_cents: int
    discount_cents: int
    total_cents: int
    items: list = field(default_factory=list)


class InsufficientInventoryError(ValidationError):
    pass


class EmptyCartError(ValidationError):
    pass


class OrderPricingService:
    def __init__(self):
        self.tax_provider = get_tax_provider()

    def calculate_total(self, *, subtotal_cents: int, shipping_cents: int, destination_state: str) -> dict:
        address = ShippingAddress(address_line_1="", address_line_2="", city="", state=destination_state, postal_code="", country="US")
        result = self.tax_provider.calculate_tax(
            TaxQuoteRequest(
                taxable_subtotal_cents=subtotal_cents,
                shipping_cents=shipping_cents,
                destination=address,
                currency="USD",
            )
        )
        tax_cents = int(getattr(result, "tax_cents", 0))
        return {
            "tax_cents": tax_cents,
            "total_cents": subtotal_cents + shipping_cents + tax_cents,
        }


class FundraiserAttributionService:
    @staticmethod
    def resolve_fundraiser_code(*, user, submitted_code: str | None = None) -> str:
        if hasattr(user, "is_seller") and user.is_seller():
            return user.get_username()
        return submitted_code or ""

    @staticmethod
    def resolve_campaign_by_slug(*, campaign_slug: str | None):
        if not campaign_slug:
            return None
        campaign = FundraiserCampaign.objects.filter(slug=campaign_slug, is_active=True).first()
        if not campaign:
            raise ValidationError("Fundraiser campaign was not found.")
        if not campaign.is_accepting_orders():
            raise ValidationError("Fundraiser campaign is not currently accepting attributed orders.")
        return campaign


class CheckoutService:
    def __init__(self):
        self.tax_provider = get_tax_provider()
        self.fulfillment_service = FulfillmentService()

    @staticmethod
    def _cart_weight_oz(items, default_oz: float) -> float:
        total = sum(float(item.sku.weight_ounces or default_oz) * item.quantity for item in items)
        return max(total, default_oz)

    def _estimate_shipping_cents(self, *, items: list, destination_state: str, postal_code: str = "", country: str = "US") -> int:
        from core.runtime_settings import get_runtime_setting

        fallback_cents = int(get_runtime_setting("estimated_shipping_cents", 899) or 899)

        from_postal = (get_runtime_setting("shipping_from_postal_code", "") or "").strip()
        from_country = (get_runtime_setting("shipping_from_country", "US") or "US").strip()
        if not from_postal:
            return fallback_cents

        try:
            provider = (get_runtime_setting("shipping_provider", "pitney_bowes") or "pitney_bowes").strip()
            carrier = get_shipping_carrier(provider)
            default_oz = float(get_runtime_setting("shipping_default_weight_oz", 16) or 16)
            package = PackageInput(weight_oz=self._cart_weight_oz(items, default_oz))
            to_address = AddressInput(
                recipient_name="Estimate",
                address_line_1="",
                city="",
                state=(destination_state or "").strip(),
                postal_code=(postal_code or "").strip(),
                country=(country or "US").strip().upper(),
            )
            quotes = carrier.get_rates(
                RateRequest(
                    from_postal_code=from_postal,
                    from_country=from_country,
                    to_address=to_address,
                    package=package,
                    order_reference="cart-estimate",
                )
            )
            if quotes:
                base_cents = min(max(int(q.rate_cents), 0) for q in quotes)
                markup_pct = float(get_runtime_setting("shipping_markup_percent", 10) or 10)
                return int(round(base_cents * (1 + markup_pct / 100)))
        except Exception:
            pass

        return fallback_cents

    def calculate_totals(self, cart: Cart, destination_state: str, postal_code: str = "", country: str = "US") -> CheckoutSummary:
        """
        Server-authoritative total calculation.
        Browser-submitted prices are never used — this is the only source of truth.
        """
        items = list(cart.items.select_related("sku__product").all())
        if not items:
            raise EmptyCartError("Cart is empty.")

        unavailable = [item.sku.sku_code for item in items if not item.sku.is_purchasable]
        if unavailable:
            raise ValidationError(
                f"The following items are no longer available: {', '.join(unavailable)}"
            )

        subtotal_cents = sum(int(item.sku.retail_price * 100) * item.quantity for item in items)
        shipping_cents = self._estimate_shipping_cents(
            items=items,
            destination_state=destination_state,
            postal_code=postal_code,
            country=country,
        )

        discount_cents = 0
        if cart.coupon_code:
            from coupons.services import CouponService

            quote = CouponService.quote_discount(cart=cart, user=cart.user)
            if quote:
                discount_cents = int(quote.discount_cents or 0)

        address = ShippingAddress(
            address_line_1="",
            address_line_2="",
            city="",
            state=destination_state,
            postal_code=postal_code,
            country=(country or "US").upper(),
        )
        result = self.tax_provider.calculate_tax(
            TaxQuoteRequest(
                taxable_subtotal_cents=max(0, subtotal_cents - discount_cents),
                shipping_cents=shipping_cents,
                destination=address,
                currency="USD",
                cart_id=cart.id,
            )
        )
        tax_cents = int(getattr(result, "tax_cents", 0))

        item_data = [
            {
                "sku": item.sku,
                "product": item.sku.product,
                "quantity": item.quantity,
                "unit_price_cents": int(item.sku.retail_price * 100),
                "line_total_cents": int(item.sku.retail_price * 100) * item.quantity,
            }
            for item in items
        ]

        return CheckoutSummary(
            subtotal_cents=subtotal_cents,
            tax_cents=tax_cents,
            shipping_cents=shipping_cents,
            discount_cents=discount_cents,
            total_cents=max(0, subtotal_cents - discount_cents + tax_cents + shipping_cents),
            items=item_data,
        )

    @staticmethod
    def _validate_payment_result(payment_result: dict) -> None:
        payment_status = (payment_result or {}).get("status", "")
        provider_ref = (payment_result or {}).get("provider_ref", "")
        allow_stub = getattr(settings, "ALLOW_STUB_CHECKOUT_PAYMENT", False)
        if payment_status not in {"captured", "confirmed"}:
            raise ValidationError("Payment was not confirmed.")
        if provider_ref.startswith("stub-") and not allow_stub:
            raise ValidationError("Stub payment is disabled. Confirm payment before placing the order.")

    @staticmethod
    def _ensure_coupon_valid(cart: Cart) -> None:
        if not cart.coupon_code:
            return
        from coupons.services import CouponService

        CouponService.get_coupon_or_error(code=cart.coupon_code)

    @staticmethod
    def _clear_inactive_attribution(attribution) -> None:
        attribution.campaign = None
        attribution.team_ref = None
        attribution.seller_store = None
        attribution.share_link = None
        attribution.fundraiser_campaign = ""
        attribution.team = ""
        attribution.seller = ""
        attribution.save(
            update_fields=[
                "campaign",
                "team_ref",
                "seller_store",
                "share_link",
                "fundraiser_campaign",
                "team",
                "seller",
                "updated_at",
            ]
        )

    def _resolve_server_attribution(self, checkout_input: CheckoutInput, fundraiser_campaign, team, seller):
        if fundraiser_campaign is not None and team is not None and seller is not None:
            return fundraiser_campaign, team, seller

        attribution = (
            CartAttribution.objects.select_related(
                "campaign",
                "team_ref",
                "seller_store__campaign",
                "seller_store__team",
                "share_link",
            )
            .filter(cart=checkout_input.cart)
            .first()
        )
        if not attribution:
            return fundraiser_campaign, team, seller

        if attribution.seller_store_id:
            seller = seller or attribution.seller_store
            fundraiser_campaign = fundraiser_campaign or attribution.seller_store.campaign
            team = team or attribution.seller_store.team
        else:
            fundraiser_campaign = fundraiser_campaign or attribution.campaign
            team = team or attribution.team_ref

        if fundraiser_campaign and not fundraiser_campaign.is_accepting_orders():
            fundraiser_campaign = None
            team = None
            seller = None
            self._clear_inactive_attribution(attribution)
        return fundraiser_campaign, team, seller

    @staticmethod
    def _build_order_model(*, summary: CheckoutSummary, checkout_input: CheckoutInput, fundraiser_campaign, team, seller) -> Order:
        shipping = checkout_input.shipping
        billing = checkout_input.billing or checkout_input.shipping
        return Order(
            customer=checkout_input.user,
            guest_email=checkout_input.guest_email,
            guest_phone=checkout_input.guest_phone,
            shipping_recipient_name=shipping.recipient_name,
            shipping_phone=shipping.phone,
            shipping_address_line_1=shipping.address_line_1,
            shipping_address_line_2=shipping.address_line_2,
            shipping_city=shipping.city,
            shipping_state=shipping.state,
            shipping_postal_code=shipping.postal_code,
            shipping_country=shipping.country,
            billing_same_as_shipping=(checkout_input.billing is None),
            billing_recipient_name=billing.recipient_name,
            billing_address_line_1=billing.address_line_1,
            billing_address_line_2=billing.address_line_2,
            billing_city=billing.city,
            billing_state=billing.state,
            billing_postal_code=billing.postal_code,
            billing_country=billing.country,
            subtotal_cents=summary.subtotal_cents,
            tax_cents=summary.tax_cents,
            shipping_cents=summary.shipping_cents,
            discount_cents=summary.discount_cents,
            total_cents=summary.total_cents,
            coupon_code=checkout_input.cart.coupon_code,
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
            fundraiser_campaign=fundraiser_campaign,
            team=team,
            seller=seller,
        )

    @staticmethod
    def _create_items_and_decrement_inventory(order: Order, summary: CheckoutSummary) -> None:
        sku_ids = [item["sku"].pk for item in summary.items]
        locked_skus = {s.pk: s for s in SKU.objects.select_for_update().filter(pk__in=sku_ids)}

        for item in summary.items:
            sku = locked_skus[item["sku"].pk]
            if sku.inventory_quantity < item["quantity"]:
                raise InsufficientInventoryError(
                    f"'{sku.sku_code}' only has {sku.inventory_quantity} unit(s) remaining."
                )
            sku.decrease_inventory(item["quantity"], payment_confirmed=True)

            OrderItem.objects.create(
                order=order,
                product=item["product"],
                sku=sku,
                product_name_snapshot=item["product"].name,
                sku_snapshot={
                    "sku_code": sku.sku_code,
                    "size": sku.size,
                    "retail_price": str(sku.retail_price),
                },
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
                line_total_cents=item["line_total_cents"],
                weight_ounces=sku.weight_ounces,
                fundraiser_eligible=item["product"].fundraiser_eligible,
            )

    @staticmethod
    def _record_payment(order: Order, summary: CheckoutSummary, payment_result: dict, actor) -> None:
        """
        Attach the payment record to the order.

        When the charge was made through the Poynt Collect flow, a
        PaymentTransaction already exists (it was created before the provider
        was called, so that failed and ambiguous attempts are recorded too). In
        that case link it rather than writing a second row — an order must
        never have two transactions claiming to have taken the money.
        """
        existing_id = payment_result.get("payment_transaction_id")
        if existing_id:
            updated = PaymentTransaction.objects.filter(pk=existing_id, order__isnull=True).update(
                order=order
            )
            if updated:
                return
            # Already linked to this order: nothing further to do.
            if PaymentTransaction.objects.filter(pk=existing_id, order=order).exists():
                return

        PaymentTransaction.objects.create(
            order=order,
            provider=payment_result.get("provider", "unknown"),
            provider_transaction_id=payment_result.get("provider_ref", ""),
            amount_cents=summary.total_cents,
            currency="USD",
            status=TxPaymentStatus.CAPTURED,
            provider_metadata=payment_result,
            created_by=actor,
        )

    @staticmethod
    def _log_order_payment_event(order: Order, summary: CheckoutSummary, payment_result: dict, actor, django_request) -> None:
        log_audit_event(
            action=AuditAction.PAYMENT_EVENT,
            message="Order created and payment captured",
            actor=actor,
            request=django_request,
            target=order,
            metadata={
                "total_cents": summary.total_cents,
                "provider": payment_result.get("provider"),
                "order_number": order.order_number,
            },
        )

    @staticmethod
    def _deactivate_cart(cart: Cart) -> None:
        cart.is_active = False
        cart.save(update_fields=["is_active", "updated_at"])

    @staticmethod
    def _record_share_link_conversion(cart: Cart) -> None:
        attribution = CartAttribution.objects.select_related("share_link").filter(cart=cart).first()
        if attribution and attribution.share_link_id:
            from sharing.models import ShareLink
            from django.db.models import F

            ShareLink.objects.filter(id=attribution.share_link_id).update(
                conversion_count=F("conversion_count") + 1,
                last_converted_at=timezone.now(),
            )

    @staticmethod
    def _record_coupon_redemption(order: Order, checkout_input: CheckoutInput) -> None:
        if not order.coupon_code:
            return
        from coupons.services import CouponService

        CouponService.record_redemption_for_order(
            order=order,
            user=checkout_input.user if getattr(checkout_input.user, "is_authenticated", False) else None,
            coupon_code=order.coupon_code,
        )

    @staticmethod
    def _notify_order_created(order: Order) -> None:
        if not order.customer_id:
            return
        from notifications.center import NotificationCenterService

        NotificationCenterService.notify_new_order(user=order.customer, order=order)

    @transaction.atomic
    def create_confirmed_order(
        self,
        *,
        summary: CheckoutSummary,
        checkout_input: CheckoutInput,
        payment_result: dict,
        fundraiser_campaign=None,
        team=None,
        seller=None,
        actor=None,
        django_request=None,
    ) -> Order:
        """
        Called after payment is confirmed by the provider.

        Atomically:
          1. Creates the Order record
          2. Locks SKU rows (SELECT FOR UPDATE) to prevent concurrent oversell
          3. Decrements inventory for each item
          4. Snapshots product/SKU data into OrderItem rows
          5. Records the PaymentTransaction
          6. Deactivates the cart

        Raises InsufficientInventoryError if any SKU sells out between
        calculate_totals() and this call.
        """
        self._validate_payment_result(payment_result)
        self._ensure_coupon_valid(checkout_input.cart)
        fundraiser_campaign, team, seller = self._resolve_server_attribution(
            checkout_input,
            fundraiser_campaign,
            team,
            seller,
        )

        order = self._build_order_model(
            summary=summary,
            checkout_input=checkout_input,
            fundraiser_campaign=fundraiser_campaign,
            team=team,
            seller=seller,
        )
        order.full_clean()
        order.save()

        self._create_items_and_decrement_inventory(order, summary)
        self._record_payment(order, summary, payment_result, actor)
        self._log_order_payment_event(order, summary, payment_result, actor, django_request)
        self._deactivate_cart(checkout_input.cart)

        try:
            self._notify_order_created(order)
        except Exception:
            pass

        try:
            self._record_share_link_conversion(checkout_input.cart)
        except Exception:
            pass

        self._record_coupon_redemption(order, checkout_input)

        return order

    def post_order_tasks(self, order: Order, *, actor=None, django_request=None) -> None:
        """
        Runs outside the atomic block — failures here don't roll back the order.
        Queues fulfillment and sends confirmation notifications.
        """
        self._queue_fulfillment(order, actor=actor, django_request=django_request)
        self._send_customer_confirmation(order)
        self._alert_staff(order)

    def _queue_fulfillment(self, order: Order, *, actor=None, django_request=None) -> None:
        FulfillmentRecord.objects.get_or_create(order=order)
        self.fulfillment_service.queue_for_packing(
            FulfillmentRequest(
                order_reference=str(order.order_number or order.pk),
                warehouse_code="main",
            ),
            actor=actor,
            django_request=django_request,
        )

    def _send_customer_confirmation(self, order: Order) -> None:
        recipient = order.contact_email
        if not recipient:
            return
        OrderNotification.objects.create(
            order=order,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=f"Order Confirmed — {order.order_number or order.pk}",
            body=(
                f"Thank you! Your order {order.order_number} has been placed. "
                f"Total: ${order.total_cents / 100:.2f}."
            ),
            status=NotificationStatus.SENT,
            sent_at=timezone.now(),
        )

    def _alert_staff(self, order: Order) -> None:
        OrderNotification.objects.create(
            order=order,
            channel=NotificationChannel.EMAIL,
            recipient="staff@popcornnsuch.local",
            subject=f"New Order — {order.order_number or order.pk}",
            body=f"Order {order.order_number} placed for ${order.total_cents / 100:.2f}.",
            status=NotificationStatus.SENT,
            sent_at=timezone.now(),
        )
