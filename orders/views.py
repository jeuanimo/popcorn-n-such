import datetime
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import DetailView, ListView, View

from cart.models import Cart, CartItem
from core.security import OwnerFilteredQuerysetMixin, RoleRequiredMixin
from payments.gateways.registry import get_payment_gateway

from .forms import CheckoutForm
from .models import (
    Order,
    OrderItem,
    OrderStatus,
    OrderSubscription,
    OrderSubscriptionItem,
    SubscriptionInterval,
    SubscriptionStatus,
)
from .services import AddressData, CheckoutInput, CheckoutService

logger = logging.getLogger(__name__)

_CART_VIEW = "cart:view"
_CHECKOUT_URL = "orders:checkout"
_CHECKOUT_REVIEW_URL = "orders:checkout-review"
_SUBSCRIPTIONS_URL = "orders:subscriptions"
_CART_EXPIRED_MSG = "Your cart has expired. Please start over."


def _get_active_cart(request) -> Cart | None:
    if request.user.is_authenticated:
        return Cart.objects.filter(user=request.user, is_active=True).first()
    session_key = request.session.session_key
    if not session_key:
        return None
    return Cart.objects.filter(session_key=session_key, user__isnull=True, is_active=True).first()


class StaffOrderListView(RoleRequiredMixin, ListView):
    model = Order
    template_name = "orders/staff_order_list.html"
    allowed_roles = ("staff", "admin")
    paginate_by = 40
    context_object_name = "orders"

    def get_queryset(self):
        qs = Order.objects.select_related("customer").order_by("-created_at")
        status = self.request.GET.get("status", "")
        q = self.request.GET.get("q", "").strip()
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(
                Q(order_number__icontains=q)
                | Q(customer__first_name__icontains=q)
                | Q(customer__last_name__icontains=q)
                | Q(customer__email__icontains=q)
                | Q(guest_email__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = OrderStatus.choices
        ctx["selected_status"] = self.request.GET.get("status", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class CustomerOrderListView(RoleRequiredMixin, OwnerFilteredQuerysetMixin, ListView):
    model = Order
    template_name = "orders/order_list.html"
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager")
    owner_field = "customer"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .prefetch_related("shipping_labels")
            .order_by("-created_at")
        )


class CustomerOrderDetailView(RoleRequiredMixin, OwnerFilteredQuerysetMixin, DetailView):
    model = Order
    template_name = "orders/order_detail.html"
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager")
    owner_field = "customer"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("shipping_labels", "items__sku__product")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["interval_choices"] = SubscriptionInterval.choices
        active_label = (
            self.object.shipping_labels.filter(is_voided=False).order_by("-created_at").first()
        )
        ctx["active_label"] = active_label
        if active_label and active_label.provider != "draft":
            ctx["tracking_events"] = list(active_label.events.order_by("-event_timestamp")[:20])
        else:
            ctx["tracking_events"] = []
        return ctx


class CheckoutView(View):
    template_name = "orders/checkout.html"

    def _render(self, request, form, cart):
        return render(request, self.template_name, {"form": form, "cart": cart})

    def get(self, request):
        cart = _get_active_cart(request)
        if not cart or not cart.items.exists():
            messages.warning(request, "Your cart is empty.")
            return redirect(_CART_VIEW)

        initial = {"country": "US"}
        if request.user.is_authenticated:
            initial["guest_email"] = request.user.email
            initial["guest_phone"] = getattr(request.user, "phone_number", "")
            default_addr = request.user.saved_addresses.filter(is_default=True).first()
            if default_addr:
                initial.update(
                    {
                        "recipient_name": default_addr.recipient_name,
                        "address_line_1": default_addr.address_line_1,
                        "address_line_2": default_addr.address_line_2,
                        "city": default_addr.city,
                        "state": default_addr.state,
                        "postal_code": default_addr.postal_code,
                        "country": default_addr.country,
                    }
                )

        return self._render(request, CheckoutForm(initial=initial), cart)

    def post(self, request):
        cart = _get_active_cart(request)
        if not cart or not cart.items.exists():
            return redirect(_CART_VIEW)

        form = CheckoutForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, cart)

        data = form.cleaned_data

        if not request.user.is_authenticated and not data.get("guest_email"):
            form.add_error("guest_email", "Email is required for guest checkout.")
            return self._render(request, form, cart)

        service = CheckoutService()
        try:
            summary = service.calculate_totals(
                cart,
                data["state"],
                postal_code=data.get("postal_code", ""),
                country=data.get("country", "US"),
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return self._render(request, form, cart)
        except Exception:
            logger.exception("Unexpected error calculating checkout totals")
            messages.error(request, "Unable to calculate order totals. Please try again.")
            return self._render(request, form, cart)

        request.session["checkout_data"] = {
            "guest_email": data.get("guest_email", ""),
            "guest_phone": data.get("guest_phone", ""),
            "recipient_name": data["recipient_name"],
            "shipping_phone": data.get("shipping_phone", ""),
            "address_line_1": data["address_line_1"],
            "address_line_2": data.get("address_line_2", ""),
            "city": data["city"],
            "state": data["state"],
            "postal_code": data["postal_code"],
            "country": data.get("country", "US"),
            "cart_id": cart.pk,
        }
        request.session["checkout_summary"] = {
            "subtotal_cents": summary.subtotal_cents,
            "tax_cents": summary.tax_cents,
            "shipping_cents": summary.shipping_cents,
            "discount_cents": summary.discount_cents,
            "total_cents": summary.total_cents,
        }

        return redirect("orders:checkout-review")


class CheckoutReviewView(View):
    template_name = "orders/checkout_review.html"

    def _payment_methods(self):
        active_provider = (getattr(settings, "PAYMENTS_PROVIDER", "godaddy") or "godaddy").lower().strip()
        label_map = {
            "godaddy": "GoDaddy Payments",
            "stripe": "Stripe",
            "paypal": "PayPal",
        }
        return [{"key": active_provider, "label": label_map.get(active_provider, active_provider.title())}]

    def _allowed_payment_hosts(self, request):
        allowed_hosts = {request.get_host()}
        raw_hosts = str(getattr(settings, "GODADDY_PAYMENTS_ALLOWED_REDIRECT_HOSTS", "") or "")
        for host in raw_hosts.split(","):
            host = host.strip()
            if host:
                allowed_hosts.add(host)
        return allowed_hosts

    def _recalculate_summary(self, request, service, cart, checkout_data):
        try:
            return service.calculate_totals(
                cart,
                checkout_data["state"],
                postal_code=checkout_data.get("postal_code", ""),
                country=checkout_data.get("country", "US"),
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return None
        except Exception:
            logger.exception("Unexpected error recalculating totals before order creation")
            messages.error(request, "Could not confirm your order. Please try again.")
            return None

    def _build_checkout_input(self, request, cart, checkout_data):
        shipping = AddressData(
            recipient_name=checkout_data["recipient_name"],
            phone=checkout_data.get("shipping_phone", ""),
            address_line_1=checkout_data["address_line_1"],
            address_line_2=checkout_data.get("address_line_2", ""),
            city=checkout_data["city"],
            state=checkout_data["state"],
            postal_code=checkout_data["postal_code"],
            country=checkout_data.get("country", "US"),
        )
        return CheckoutInput(
            cart=cart,
            shipping=shipping,
            guest_email=checkout_data.get("guest_email", ""),
            guest_phone=checkout_data.get("guest_phone", ""),
            user=request.user if request.user.is_authenticated else None,
        )

    def _select_payment_method(self, request, payment_methods):
        selected_payment_method = (request.POST.get("payment_method") or "").strip().lower()
        allowed_methods = {row["key"] for row in payment_methods}
        if not selected_payment_method:
            messages.error(request, "Please select a payment option.")
            return None
        if selected_payment_method not in allowed_methods:
            messages.error(request, "Selected payment option is not available.")
            return None
        request.session["selected_payment_method"] = selected_payment_method
        return selected_payment_method

    def _start_hosted_session(self, request, *, selected_payment_method, summary, payment_methods, checkout_data, cart):
        try:
            gateway = get_payment_gateway(selected_payment_method)
            return_url = request.build_absolute_uri(reverse("orders:checkout-payment-return"))
            cancel_url = request.build_absolute_uri(reverse(_CHECKOUT_REVIEW_URL))
            payment_session = gateway.create_payment_session(
                order_id=cart.pk,
                amount_cents=summary.total_cents,
                currency="USD",
                idempotency_key=f"cart-{cart.pk}-review",
                return_url=return_url,
                cancel_url=cancel_url,
                actor=request.user if request.user.is_authenticated else None,
                request=request,
                metadata={
                    "cart_id": cart.pk,
                    "customer_email": checkout_data.get("guest_email", ""),
                },
            )
        except Exception as exc:
            logger.exception("Could not start hosted payment session")
            messages.error(request, f"Could not start payment session: {exc}")
            return redirect(_CHECKOUT_REVIEW_URL)

        if not payment_session.checkout_url:
            messages.error(request, "Payment provider did not return a checkout link.")
            return redirect(_CHECKOUT_REVIEW_URL)

        if not url_has_allowed_host_and_scheme(
            payment_session.checkout_url,
            allowed_hosts=self._allowed_payment_hosts(request),
            require_https=not settings.DEBUG,
        ):
            logger.warning("Blocked untrusted hosted payment redirect URL: %s", payment_session.checkout_url)
            messages.error(request, "Payment provider returned an untrusted redirect URL.")
            return redirect(_CHECKOUT_REVIEW_URL)

        request.session["pending_payment"] = {
            "provider": selected_payment_method,
            "provider_session_id": payment_session.provider_session_id or "",
            "provider_transaction_id": payment_session.provider_transaction_id or "",
            "cart_id": cart.pk,
        }
        return render(
            request,
            "orders/payment_redirect.html",
            {
                "checkout_url": payment_session.checkout_url,
                "provider_label": {m["key"]: m["label"] for m in payment_methods}.get(
                    selected_payment_method,
                    "Payment Provider",
                ),
            },
        )

    def _create_order_with_stub_payment(self, request, *, service, summary, checkout_input):
        payment_result = {
            "provider": "godaddy",
            "status": "captured",
            "provider_ref": f"stub-{checkout_input.cart.pk}",
        }
        try:
            return service.create_confirmed_order(
                summary=summary,
                checkout_input=checkout_input,
                payment_result=payment_result,
                actor=request.user if request.user.is_authenticated else None,
                django_request=request,
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return None
        except Exception:
            logger.exception("Unexpected error creating order")
            messages.error(request, "Something went wrong processing your order. Please try again.")
            return None

    def get(self, request):
        checkout_data = request.session.get("checkout_data")
        summary_data = request.session.get("checkout_summary")
        if not checkout_data or not summary_data:
            return redirect(_CHECKOUT_URL)

        cart = _get_active_cart(request)
        if not cart:
            messages.warning(request, _CART_EXPIRED_MSG)
            return redirect(_CART_VIEW)

        return render(
            request,
            self.template_name,
            {
                "checkout_data": checkout_data,
                "summary": summary_data,
                "cart": cart,
                "payment_methods": self._payment_methods(),
                "selected_payment_method": request.session.get("selected_payment_method", ""),
                "stub_checkout_enabled": bool(getattr(settings, "ALLOW_STUB_CHECKOUT_PAYMENT", False)),
            },
        )

    def post(self, request):
        """
        Submits the order after the customer reviews the summary.

        In production, replace the stub payment_result with the real provider
        payload from a tokenized card charge or redirect callback.
        """
        checkout_data = request.session.get("checkout_data")
        if not checkout_data:
            return redirect(_CHECKOUT_URL)

        cart_id = checkout_data.get("cart_id")
        cart = Cart.objects.filter(pk=cart_id, is_active=True).first()
        if not cart:
            messages.error(request, _CART_EXPIRED_MSG)
            return redirect(_CART_VIEW)

        service = CheckoutService()
        summary = self._recalculate_summary(request, service, cart, checkout_data)
        if not summary:
            return redirect(_CHECKOUT_URL)

        checkout_input = self._build_checkout_input(request, cart, checkout_data)

        payment_methods = self._payment_methods()
        selected_payment_method = self._select_payment_method(request, payment_methods)
        if not selected_payment_method:
            return redirect(_CHECKOUT_REVIEW_URL)

        if not getattr(settings, "ALLOW_STUB_CHECKOUT_PAYMENT", False):
            return self._start_hosted_session(
                request,
                selected_payment_method=selected_payment_method,
                summary=summary,
                payment_methods=payment_methods,
                checkout_data=checkout_data,
                cart=cart,
            )

        order = self._create_order_with_stub_payment(
            request,
            service=service,
            summary=summary,
            checkout_input=checkout_input,
        )
        if not order:
            return redirect(_CHECKOUT_URL)

        # Dispatch fulfillment + notifications as a background task so the
        # customer is not held waiting for SMTP or fulfillment API calls.
        from orders.tasks import run_post_order_tasks
        run_post_order_tasks.delay(order.id)

        request.session.pop("checkout_data", None)
        request.session.pop("checkout_summary", None)
        request.session.pop("pending_payment", None)

        return redirect("orders:checkout-complete", order_number=order.order_number or order.pk)


class CheckoutPaymentReturnView(View):
    def _load_pending_checkout_context(self, request):
        pending_payment = request.session.get("pending_payment")
        checkout_data = request.session.get("checkout_data")
        if not pending_payment or not checkout_data:
            messages.error(request, "Payment session expired. Please review checkout again.")
            return None, None, None

        if str(pending_payment.get("cart_id", "")) != str(checkout_data.get("cart_id", "")):
            request.session.pop("pending_payment", None)
            return None, None, HttpResponseBadRequest("Payment session does not match current cart.")

        cart = Cart.objects.filter(pk=checkout_data.get("cart_id"), is_active=True).first()
        if not cart:
            messages.error(request, _CART_EXPIRED_MSG)
            return None, None, redirect(_CART_VIEW)
        return pending_payment, checkout_data, cart

    def _recalculate_summary(self, request, service, cart, checkout_data):
        try:
            return service.calculate_totals(
                cart,
                checkout_data["state"],
                postal_code=checkout_data.get("postal_code", ""),
                country=checkout_data.get("country", "US"),
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return None
        except Exception:
            logger.exception("Unexpected error recalculating totals after payment")
            messages.error(request, "Could not confirm your order. Please try again.")
            return None

    def _verify_pending_payment(self, request, pending_payment):
        try:
            gateway = get_payment_gateway(pending_payment.get("provider", ""))
            verification = gateway.verify_payment(
                provider_transaction_id=pending_payment.get("provider_transaction_id") or None,
                provider_session_id=pending_payment.get("provider_session_id") or None,
                actor=request.user if request.user.is_authenticated else None,
                request=request,
            )
        except Exception as exc:
            logger.exception("Hosted payment verification failed")
            messages.error(request, f"Could not verify payment: {exc}")
            return None

        if not verification.is_confirmed:
            status = verification.status or "pending"
            messages.error(request, f"Payment is not confirmed yet (status: {status}).")
            return None
        return verification

    @staticmethod
    def _build_checkout_input(request, cart, checkout_data):
        shipping = AddressData(
            recipient_name=checkout_data["recipient_name"],
            phone=checkout_data.get("shipping_phone", ""),
            address_line_1=checkout_data["address_line_1"],
            address_line_2=checkout_data.get("address_line_2", ""),
            city=checkout_data["city"],
            state=checkout_data["state"],
            postal_code=checkout_data["postal_code"],
            country=checkout_data.get("country", "US"),
        )
        return CheckoutInput(
            cart=cart,
            shipping=shipping,
            guest_email=checkout_data.get("guest_email", ""),
            guest_phone=checkout_data.get("guest_phone", ""),
            user=request.user if request.user.is_authenticated else None,
        )

    def get(self, request):
        pending_payment, checkout_data, cart = self._load_pending_checkout_context(request)
        if hasattr(cart, "status_code"):
            return cart
        if cart is None:
            return redirect(_CHECKOUT_REVIEW_URL)

        service = CheckoutService()
        summary = self._recalculate_summary(request, service, cart, checkout_data)
        if not summary:
            return redirect(_CHECKOUT_URL)

        verification = self._verify_pending_payment(request, pending_payment)
        if not verification:
            return redirect(_CHECKOUT_REVIEW_URL)

        checkout_input = self._build_checkout_input(request, cart, checkout_data)
        payment_result = {
            "provider": pending_payment.get("provider", "godaddy"),
            "status": "confirmed",
            "provider_ref": verification.provider_transaction_id or pending_payment.get("provider_session_id", ""),
            "verification": verification.raw or {},
        }

        try:
            order = service.create_confirmed_order(
                summary=summary,
                checkout_input=checkout_input,
                payment_result=payment_result,
                actor=request.user if request.user.is_authenticated else None,
                django_request=request,
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(_CHECKOUT_URL)
        except Exception:
            logger.exception("Unexpected error creating order after payment confirmation")
            messages.error(request, "Something went wrong processing your order. Please try again.")
            return redirect(_CHECKOUT_URL)

        from orders.tasks import run_post_order_tasks
        run_post_order_tasks.delay(order.id)

        request.session.pop("checkout_data", None)
        request.session.pop("checkout_summary", None)
        request.session.pop("pending_payment", None)

        return redirect("orders:checkout-complete", order_number=order.order_number or order.pk)


class CheckoutCompleteView(View):
    template_name = "orders/checkout_complete.html"

    def get(self, request, order_number: str):
        if request.user.is_authenticated:
            order = Order.objects.filter(order_number=order_number, customer=request.user).first()
        else:
            order = Order.objects.filter(order_number=order_number).first()

        if not order:
            messages.warning(request, "Order not found.")
            return redirect("core:home")

        return render(request, self.template_name, {"order": order})


@login_required
def reorder_view(request, order_id: int):
    if request.method != "POST":
        return redirect("orders:my-orders")

    order = get_object_or_404(Order, id=order_id, customer=request.user)
    cart, _ = request.user.carts.get_or_create(
        is_active=True, defaults={"session_key": request.session.session_key or ""}
    )

    added_count = 0
    for line_item in OrderItem.objects.filter(order=order).select_related("sku"):
        if not line_item.sku.is_purchasable:
            continue
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            sku=line_item.sku,
            defaults={"quantity": line_item.quantity},
        )
        if not created:
            cart_item.quantity += line_item.quantity
            cart_item.save(update_fields=["quantity", "updated_at"])
        added_count += 1

    if added_count:
        messages.success(request, "Previous order items were added to your cart.")
    else:
        messages.warning(request, "No reorderable items were found for that order.")

    return redirect(_CART_VIEW)


class SubscriptionsView(RoleRequiredMixin, ListView):
    template_name = "orders/subscriptions.html"
    context_object_name = "subscriptions"
    allowed_roles = ("customer", "seller", "team_captain", "organization_manager")

    def get_queryset(self):
        return (
            OrderSubscription.objects.filter(user=self.request.user)
            .prefetch_related("items__sku__product")
            .select_related("source_order")
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["interval_choices"] = SubscriptionInterval.choices
        return ctx


@login_required
def create_subscription_view(request, order_id: int):
    if request.method != "POST":
        return redirect("orders:my-orders")

    order = get_object_or_404(Order, id=order_id, customer=request.user)
    interval = (request.POST.get("interval") or "").strip()
    valid_intervals = {k for k, _ in SubscriptionInterval.choices}
    if interval not in valid_intervals:
        messages.error(request, "Please select a valid subscription interval.")
        return redirect("orders:order-detail", pk=order_id)

    items = list(OrderItem.objects.filter(order=order).select_related("sku"))
    purchasable = [i for i in items if i.sku.is_purchasable]
    if not purchasable:
        messages.error(request, "None of the items in this order are available for subscription.")
        return redirect("orders:order-detail", pk=order_id)

    next_date = datetime.date.today() + datetime.timedelta(
        days={
            SubscriptionInterval.WEEKLY: 7,
            SubscriptionInterval.BIWEEKLY: 14,
            SubscriptionInterval.MONTHLY: 30,
            SubscriptionInterval.EVERY_TWO_MONTHS: 60,
        }[interval]
    )

    sub = OrderSubscription.objects.create(
        user=request.user,
        source_order=order,
        interval=interval,
        next_order_date=next_date,
    )
    OrderSubscriptionItem.objects.bulk_create(
        [OrderSubscriptionItem(subscription=sub, sku=item.sku, quantity=item.quantity) for item in purchasable]
    )

    messages.success(
        request,
        f"Subscription created! Your next order will be placed on {next_date.strftime('%B %d, %Y')}.",
    )
    return redirect(_SUBSCRIPTIONS_URL)


@login_required
def pause_subscription_view(request, subscription_id: int):
    if request.method != "POST":
        return redirect(_SUBSCRIPTIONS_URL)
    sub = get_object_or_404(OrderSubscription, id=subscription_id, user=request.user)
    if sub.status == SubscriptionStatus.ACTIVE:
        sub.status = SubscriptionStatus.PAUSED
        sub.paused_at = timezone.now()
        sub.save(update_fields=["status", "paused_at", "updated_at"])
        messages.success(request, "Subscription paused.")
    return redirect(_SUBSCRIPTIONS_URL)


@login_required
def resume_subscription_view(request, subscription_id: int):
    if request.method != "POST":
        return redirect(_SUBSCRIPTIONS_URL)
    sub = get_object_or_404(OrderSubscription, id=subscription_id, user=request.user)
    if sub.status == SubscriptionStatus.PAUSED:
        sub.advance_next_date()
        sub.status = SubscriptionStatus.ACTIVE
        sub.paused_at = None
        sub.save(update_fields=["status", "paused_at", "next_order_date", "updated_at"])
        messages.success(request, f"Subscription resumed. Next order: {sub.next_order_date.strftime('%B %d, %Y')}.")
    return redirect(_SUBSCRIPTIONS_URL)


@login_required
def cancel_subscription_view(request, subscription_id: int):
    if request.method != "POST":
        return redirect(_SUBSCRIPTIONS_URL)
    sub = get_object_or_404(OrderSubscription, id=subscription_id, user=request.user)
    if sub.status != SubscriptionStatus.CANCELLED:
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = timezone.now()
        sub.save(update_fields=["status", "cancelled_at", "updated_at"])
        messages.success(request, "Subscription cancelled.")
    return redirect(_SUBSCRIPTIONS_URL)
