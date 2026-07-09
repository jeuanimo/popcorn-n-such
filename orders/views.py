import datetime
import logging
import uuid

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
_CHECKOUT_COMPLETE_URL = "orders:checkout-complete"
_SUBSCRIPTIONS_URL = "orders:subscriptions"
_CART_EXPIRED_MSG = "Your cart has expired. Please start over."
_ORDER_CREATION_ERROR_MSG = "Something went wrong processing your order. Please try again."


def _get_active_cart(request) -> Cart | None:
    if request.user.is_authenticated:
        return Cart.objects.filter(user=request.user, is_active=True).first()
    session_key = request.session.session_key
    if not session_key:
        return None
    return Cart.objects.filter(session_key=session_key, user__isnull=True, is_active=True).first()


class ClearAllOrdersView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, *args, **kwargs):
        # Delete PROTECT-guarded children first, then orders.
        from fulfillment.models import FulfillmentRecord
        from coupons.models import CouponRedemption
        from payments.models import PaymentTransaction
        from shipping.models import ShippingLabel
        ShippingLabel.objects.all().delete()
        FulfillmentRecord.objects.all().delete()
        CouponRedemption.objects.all().delete()
        PaymentTransaction.objects.all().delete()
        count, _ = Order.objects.all().delete()
        messages.success(request, f"Cleared {count} order record(s) from the database.")
        return redirect("orders:staff-list")


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

    @staticmethod
    def _collect_ids():
        from core.runtime_settings import get_runtime_setting

        business_id = str(get_runtime_setting("godaddy_collect_business_id", getattr(settings, "GODADDY_COLLECT_BUSINESS_ID", "") or "")).strip()
        application_id = str(get_runtime_setting("godaddy_collect_application_id", getattr(settings, "GODADDY_COLLECT_APPLICATION_ID", "") or "")).strip()

        combined = str(get_runtime_setting("godaddy_collect_application_key", getattr(settings, "GODADDY_COLLECT_APPLICATION_KEY", "") or "")).strip()
        if combined and (not business_id or not application_id) and "=" in combined:
            left, right = combined.split("=", 1)
            if not business_id:
                business_id = left.strip()
            if not application_id:
                application_id = right.strip()

        return {"business_id": business_id, "application_id": application_id}

    def _poynt_collect_context(self):
        from core.runtime_settings import get_runtime_setting

        enabled = bool(get_runtime_setting("godaddy_collect_enabled", getattr(settings, "GODADDY_COLLECT_ENABLED", False)))
        sdk_url = str(get_runtime_setting("godaddy_collect_sdk_url", getattr(settings, "GODADDY_COLLECT_SDK_URL", "") or "")).strip()
        iframe_height = str(get_runtime_setting("godaddy_collect_iframe_height", getattr(settings, "GODADDY_COLLECT_IFRAME_HEIGHT", "460px") or "460px")).strip()

        recaptcha_type = str(get_runtime_setting("godaddy_collect_recaptcha_type", getattr(settings, "GODADDY_COLLECT_RECAPTCHA_TYPE", "DEFAULT") or "DEFAULT")).strip().upper()
        if recaptcha_type not in {"DEFAULT", "TEXT"}:
            recaptcha_type = "DEFAULT"

        recaptcha_text_font_size = str(
            get_runtime_setting(
                "godaddy_collect_recaptcha_text_font_size",
                getattr(settings, "GODADDY_COLLECT_RECAPTCHA_TEXT_FONT_SIZE", "14px") or "14px",
            )
        ).strip()
        recaptcha_text_color = str(
            get_runtime_setting(
                "godaddy_collect_recaptcha_text_color",
                getattr(settings, "GODADDY_COLLECT_RECAPTCHA_TEXT_COLOR", "#111827") or "#111827",
            )
        ).strip()
        recaptcha_link_color = str(
            get_runtime_setting(
                "godaddy_collect_recaptcha_link_color",
                getattr(settings, "GODADDY_COLLECT_RECAPTCHA_LINK_COLOR", "#0d6efd") or "#0d6efd",
            )
        ).strip()
        recaptcha_link_text_decoration = str(
            get_runtime_setting(
                "godaddy_collect_recaptcha_link_text_decoration",
                getattr(settings, "GODADDY_COLLECT_RECAPTCHA_LINK_TEXT_DECORATION", "underline") or "underline",
            )
        ).strip()
        charge_source = str(
            get_runtime_setting(
                "godaddy_payments_charge_source",
                getattr(settings, "GODADDY_PAYMENTS_CHARGE_SOURCE", "nonce") or "nonce",
            )
        ).strip().lower()
        if charge_source not in {"nonce", "payment_token"}:
            charge_source = "nonce"

        ids = self._collect_ids()
        is_configured = bool(sdk_url and ids["business_id"] and ids["application_id"])
        return {
            "enabled": enabled and is_configured,
            "configured": is_configured,
            "sdk_url": sdk_url,
            "telemetry_url": reverse("payments:collect-telemetry"),
            "business_id": ids["business_id"],
            "application_id": ids["application_id"],
            "iframe_height": iframe_height,
            "recaptcha_type": recaptcha_type,
            "recaptcha_text_font_size": recaptcha_text_font_size,
            "recaptcha_text_color": recaptcha_text_color,
            "recaptcha_link_color": recaptcha_link_color,
            "recaptcha_link_text_decoration": recaptcha_link_text_decoration,
            "charge_source": charge_source,
        }

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
            messages.error(request, _ORDER_CREATION_ERROR_MSG)
            return None

    @staticmethod
    def _bool_from_runtime(value) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _collect_charge_options(self):
        from core.runtime_settings import get_runtime_setting

        charge_source = str(
            get_runtime_setting(
                "godaddy_payments_charge_source",
                getattr(settings, "GODADDY_PAYMENTS_CHARGE_SOURCE", "nonce") or "nonce",
            )
        ).strip().lower()
        if charge_source not in {"nonce", "payment_token"}:
            charge_source = "nonce"

        charge_action = str(
            get_runtime_setting(
                "godaddy_payments_charge_nonce_action",
                getattr(settings, "GODADDY_PAYMENTS_CHARGE_NONCE_ACTION", "SALE") or "SALE",
            )
        ).strip().upper()

        auth_only_runtime = get_runtime_setting(
            "godaddy_payments_charge_nonce_auth_only",
            getattr(settings, "GODADDY_PAYMENTS_CHARGE_NONCE_AUTH_ONLY", False),
        )
        return {
            "charge_source": charge_source,
            "charge_action": charge_action,
            "auth_only": self._bool_from_runtime(auth_only_runtime),
        }

    def _build_collect_charge_kwargs(self, *, request, summary, checkout_input):
        receipt_email = (checkout_input.guest_email or getattr(request.user, "email", "") or "").strip()
        options = self._collect_charge_options()
        return {
            "amount_cents": summary.total_cents,
            "currency": "USD",
            "idempotency_key": f"checkout-{checkout_input.cart.pk}-{uuid.uuid4().hex[:12]}",
            "action": options["charge_action"],
            "auth_only": options["auth_only"],
            "business_id": self._collect_ids().get("business_id", ""),
            "email_receipt": bool(receipt_email),
            "receipt_email_address": receipt_email,
            "actor": request.user if request.user.is_authenticated else None,
            "request": request,
            "metadata": {
                "cart_id": checkout_input.cart.pk,
                "guest_email": checkout_input.guest_email,
            },
            "charge_source": options["charge_source"],
        }

    def _charge_via_payment_token(self, *, gateway, nonce, charge_kwargs, checkout_input):
        tokenize_details = gateway.create_payment_token(
            nonce=nonce,
            idempotency_key=f"tokenize-{checkout_input.cart.pk}-{uuid.uuid4().hex[:12]}",
            business_id=charge_kwargs["business_id"],
            actor=charge_kwargs["actor"],
            request=charge_kwargs["request"],
            metadata=charge_kwargs["metadata"],
        )
        if (tokenize_details.get("status") or "").upper() != "ACTIVE":
            raise ValueError("Payment token validation failed.")

        payment_token = (tokenize_details.get("payment_token") or "").strip()
        if not payment_token:
            raise ValueError("Payment token was not returned by provider.")

        charge_result = gateway.charge_payment_token(
            payment_token=payment_token,
            **{k: v for k, v in charge_kwargs.items() if k != "charge_source"},
        )
        return charge_result, tokenize_details

    @staticmethod
    def _build_payment_result(*, charge_result, charge_source: str, tokenize_details):
        payment_result = {
            "provider": "godaddy",
            "status": "confirmed",
            "provider_ref": charge_result.provider_transaction_id or "",
            "verification": charge_result.raw or {},
            "charge_source": charge_source,
        }
        if charge_source == "payment_token" and tokenize_details:
            payment_result["tokenize"] = {
                "status": tokenize_details.get("status", ""),
                "cvv_response": tokenize_details.get("cvv_response", ""),
                "avs_address_result": tokenize_details.get("avs_address_result", ""),
                "avs_postal_result": tokenize_details.get("avs_postal_result", ""),
                "card_status": tokenize_details.get("card_status", ""),
            }
        return payment_result

    def _execute_collect_charge(self, *, gateway, nonce, charge_kwargs, checkout_input):
        tokenize_details = None
        if charge_kwargs["charge_source"] == "payment_token":
            charge_result, tokenize_details = self._charge_via_payment_token(
                gateway=gateway,
                nonce=nonce,
                charge_kwargs=charge_kwargs,
                checkout_input=checkout_input,
            )
            return charge_result, tokenize_details

        charge_result = gateway.charge_nonce(
            nonce=nonce,
            **{k: v for k, v in charge_kwargs.items() if k != "charge_source"},
        )
        return charge_result, tokenize_details

    def _handle_collect_charge_error(self, request, exc: Exception) -> None:
        msg = str(exc).strip()
        if msg == "Payment token validation failed.":
            messages.error(request, "Payment token validation failed. Please check your card details and try again.")
            return
        if msg == "Payment token was not returned by provider.":
            messages.error(request, msg)
            return
        messages.error(request, f"Could not charge payment method: {exc}")

    def _create_order_after_collect_charge(self, request, *, service, summary, checkout_input, nonce):
        charge_kwargs = self._build_collect_charge_kwargs(
            request=request,
            summary=summary,
            checkout_input=checkout_input,
        )

        try:
            gateway = get_payment_gateway("godaddy")
            charge_result, tokenize_details = self._execute_collect_charge(
                gateway=gateway,
                nonce=nonce,
                charge_kwargs=charge_kwargs,
                checkout_input=checkout_input,
            )
        except Exception as exc:
            logger.exception("Poynt Collect nonce charge failed")
            self._handle_collect_charge_error(request, exc)
            return None

        if not charge_result.is_confirmed:
            status = charge_result.status or "pending"
            failure_message = charge_result.failure_message or ""
            if failure_message:
                messages.error(request, f"Payment was not approved (status: {status}). {failure_message}")
            else:
                messages.error(request, f"Payment was not approved (status: {status}).")
            return None

        payment_result = self._build_payment_result(
            charge_result=charge_result,
            charge_source=charge_kwargs["charge_source"],
            tokenize_details=tokenize_details,
        )

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
            logger.exception("Unexpected error creating order after collect nonce charge")
            messages.error(request, _ORDER_CREATION_ERROR_MSG)
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
                "poynt_collect": self._poynt_collect_context(),
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

        poynt_collect = self._poynt_collect_context()
        if selected_payment_method == "godaddy" and poynt_collect["enabled"]:
            nonce = (request.POST.get("poynt_nonce") or "").strip()
            if not nonce:
                messages.error(request, "Card details are required. Please enter your payment information.")
                return redirect(_CHECKOUT_REVIEW_URL)

            order = self._create_order_after_collect_charge(
                request,
                service=service,
                summary=summary,
                checkout_input=checkout_input,
                nonce=nonce,
            )
            if not order:
                return redirect(_CHECKOUT_REVIEW_URL)

            from orders.tasks import run_post_order_tasks
            run_post_order_tasks.delay(order.id)

            request.session.pop("checkout_data", None)
            request.session.pop("checkout_summary", None)
            request.session.pop("pending_payment", None)

            return redirect(_CHECKOUT_COMPLETE_URL, order_number=order.order_number or order.pk)

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

        return redirect(_CHECKOUT_COMPLETE_URL, order_number=order.order_number or order.pk)


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
            messages.error(request, _ORDER_CREATION_ERROR_MSG)
            return redirect(_CHECKOUT_URL)

        from orders.tasks import run_post_order_tasks
        run_post_order_tasks.delay(order.id)

        request.session.pop("checkout_data", None)
        request.session.pop("checkout_summary", None)
        request.session.pop("pending_payment", None)

        return redirect(_CHECKOUT_COMPLETE_URL, order_number=order.order_number or order.pk)


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
