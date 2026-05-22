from __future__ import annotations

import os

from django.conf import settings
from django.http import HttpResponseRedirect
from django.db.models import Count, F, Q
from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from dotenv import set_key

from core.security import RoleRequiredMixin
from core.forms import OperationalSettingsForm
from core.models import OperationalSettings
from payments.gateways.registry import get_payment_gateway
from dashboards.services import (
	CustomerDashboardService,
	FulfillmentDashboardService,
	OrganizationDashboardService,
	OwnerDashboardService,
	SellerDashboardService,
	TeamDashboardService,
)
from organizations.models import Organization
from sellers.models import SellerStore
from teams.models import Team


class DashboardHomeView(RoleRequiredMixin, View):
	allowed_roles = ("admin", "staff", "organization_manager", "team_captain", "seller", "customer")

	def get(self, request):
		u = request.user
		if u.is_superuser or u.has_any_role("admin"):
			return HttpResponseRedirect(reverse("dashboards:owner"))
		if u.is_staff or u.has_any_role("staff"):
			return HttpResponseRedirect(reverse("dashboards:fulfillment"))
		if u.has_any_role("organization_manager"):
			return HttpResponseRedirect(reverse("dashboards:organization"))
		if u.has_any_role("team_captain"):
			return HttpResponseRedirect(reverse("dashboards:team"))
		if u.has_any_role("seller"):
			return HttpResponseRedirect(reverse("dashboards:seller"))
		return HttpResponseRedirect(reverse("dashboards:customer"))


class OwnerDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("admin",)
	template_name = "dashboards/owner.html"

	def get(self, request):
		context = OwnerDashboardService.context(user=request.user)
		return render(request, self.template_name, context)


class FulfillmentDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")
	template_name = "dashboards/fulfillment.html"

	def get(self, request):
		context = FulfillmentDashboardService.context(user=request.user)
		return render(request, self.template_name, context)


class StaffPortalView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")
	template_name = "staff/portal.html"

	def get(self, request):
		stock_context = {
			"low_stock_skus": 0,
			"out_of_stock_skus": 0,
			"low_stock_products": 0,
			"out_of_stock_products": 0,
		}
		try:
			from products.models import Product, SKU

			low_skus_qs = SKU.objects.filter(
				is_active=True,
				product__is_active=True,
				inventory_quantity__gt=0,
				inventory_quantity__lte=F("low_stock_threshold"),
			)
			out_skus_qs = SKU.objects.filter(
				is_active=True,
				product__is_active=True,
				inventory_quantity=0,
			)

			product_stock = Product.objects.active().annotate(
				active_sku_count=Count("skus", filter=Q(skus__is_active=True), distinct=True),
				purchasable_sku_count=Count(
					"skus",
					filter=Q(skus__is_active=True, skus__inventory_quantity__gt=0),
					distinct=True,
				),
				low_stock_sku_count=Count(
					"skus",
					filter=Q(
						skus__is_active=True,
						skus__inventory_quantity__gt=0,
						skus__inventory_quantity__lte=F("skus__low_stock_threshold"),
					),
					distinct=True,
				),
			)

			stock_context = {
				"low_stock_skus": low_skus_qs.count(),
				"out_of_stock_skus": out_skus_qs.count(),
				"low_stock_products": product_stock.filter(
					purchasable_sku_count__gt=0,
					low_stock_sku_count=F("purchasable_sku_count"),
				).count(),
				"out_of_stock_products": product_stock.filter(
					active_sku_count__gt=0,
					purchasable_sku_count=0,
				).count(),
			}
		except Exception:
			pass

		stock_context["can_create_users"] = request.user.has_role("admin")
		return render(request, self.template_name, stock_context)


class OrganizationDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("organization_manager", "staff", "admin")
	template_name = "dashboards/organization.html"

	def get(self, request):
		if request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin"):
			org_id = request.GET.get("org_id")
			org = get_object_or_404(Organization, id=org_id) if org_id else Organization.objects.order_by("name").first()
		else:
			org = Organization.objects.filter(manager=request.user).order_by("name").first()
		if not org:
			return render(request, self.template_name, {"organization": None, "active_campaigns": [], "campaign_metrics": []})
		return render(request, self.template_name, OrganizationDashboardService.context(organization=org))


class TeamDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("team_captain", "staff", "admin")
	template_name = "dashboards/team.html"

	def get(self, request):
		if request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin"):
			team_id = request.GET.get("team_id")
			team = get_object_or_404(Team, id=team_id) if team_id else Team.objects.order_by("name").first()
		else:
			team = Team.objects.filter(captain=request.user, is_active=True).order_by("name").first()
		if not team:
			return render(request, self.template_name, {"team": None})
		return render(request, self.template_name, TeamDashboardService.context(team=team))


class SellerDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("seller", "staff", "admin")
	template_name = "dashboards/seller.html"

	def get(self, request):
		if request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin"):
			store_id = request.GET.get("store_id")
			store = get_object_or_404(SellerStore, id=store_id) if store_id else SellerStore.objects.order_by("-created_at").first()
		else:
			store = SellerStore.objects.filter(seller=request.user, is_active=True).order_by("-created_at").first()
		if not store:
			return render(request, self.template_name, {"store": None})
		return render(request, self.template_name, SellerDashboardService.context(store=store))


class CustomerDashboardView(RoleRequiredMixin, View):
	allowed_roles = ("customer", "staff", "admin")
	template_name = "dashboards/customer.html"

	def get(self, request):
		return render(request, self.template_name, CustomerDashboardService.context(user=request.user, request=request))


class StaffHowToView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")
	template_name = "staff/how_to.html"

	def get(self, request):
		return render(request, self.template_name, {})


class OperationalSettingsView(RoleRequiredMixin, View):
	allowed_roles = ("staff", "admin")
	template_name = "staff/operational_settings.html"
	ENV_MAP = {
		"pitney_bowes_api_key": "PITNEY_BOWES_API_KEY",
		"pitney_bowes_api_secret": "PITNEY_BOWES_API_SECRET",
		"pitney_bowes_env": "PITNEY_BOWES_ENV",
		"pitney_bowes_base_url_sandbox": "PITNEY_BOWES_BASE_URL_SANDBOX",
		"pitney_bowes_base_url_prod": "PITNEY_BOWES_BASE_URL_PROD",
		"godaddy_api_key": "GODADDY_API_KEY",
		"godaddy_api_secret": "GODADDY_API_SECRET",
		"godaddy_merchant_id": "GODADDY_MERCHANT_ID",
		"godaddy_payments_webhook_secret": "GODADDY_PAYMENTS_WEBHOOK_SECRET",
		"godaddy_payments_base_url": "GODADDY_PAYMENTS_BASE_URL",
		"godaddy_payments_create_session_path": "GODADDY_PAYMENTS_CREATE_SESSION_PATH",
		"godaddy_payments_verify_path": "GODADDY_PAYMENTS_VERIFY_PATH",
		"godaddy_payments_refund_path": "GODADDY_PAYMENTS_REFUND_PATH",
		"godaddy_payments_test_path": "GODADDY_PAYMENTS_TEST_PATH",
		"godaddy_payments_test_method": "GODADDY_PAYMENTS_TEST_METHOD",
		"godaddy_payments_allowed_redirect_hosts": "GODADDY_PAYMENTS_ALLOWED_REDIRECT_HOSTS",
		"contact_email": "CONTACT_EMAIL",
		"default_from_email": "DEFAULT_FROM_EMAIL",
		"email_host": "EMAIL_HOST",
		"email_port": "EMAIL_PORT",
		"email_host_user": "EMAIL_HOST_USER",
		"email_host_password": "EMAIL_HOST_PASSWORD",
		"email_use_tls": "EMAIL_USE_TLS",
		"shipping_provider": "SHIPPING_PROVIDER",
		"shipping_from_name": "SHIPPING_FROM_NAME",
		"shipping_from_address_line_1": "SHIPPING_FROM_ADDRESS_LINE_1",
		"shipping_from_address_line_2": "SHIPPING_FROM_ADDRESS_LINE_2",
		"shipping_from_city": "SHIPPING_FROM_CITY",
		"shipping_from_state": "SHIPPING_FROM_STATE",
		"shipping_from_postal_code": "SHIPPING_FROM_POSTAL_CODE",
		"shipping_from_country": "SHIPPING_FROM_COUNTRY",
		"shipping_default_weight_oz": "SHIPPING_DEFAULT_WEIGHT_OZ",
		"shipping_markup_percent": "SHIPPING_MARKUP_PERCENT",
		"estimated_shipping_cents": "ESTIMATED_SHIPPING_CENTS",
		"usps_client_id": "USPS_CLIENT_ID",
		"usps_client_secret": "USPS_CLIENT_SECRET",
		"usps_env": "USPS_ENV",
		"usps_base_url_sandbox": "USPS_BASE_URL_SANDBOX",
		"usps_base_url_prod": "USPS_BASE_URL_PROD",
		"label_printer_name": "LABEL_PRINTER_NAME",
		"label_printer_ip": "LABEL_PRINTER_IP",
	}
	SECRET_FIELDS = {
		"pitney_bowes_api_secret",
		"godaddy_api_secret",
		"godaddy_payments_webhook_secret",
		"email_host_password",
		"usps_client_secret",
	}

	def get(self, request):
		initial = {}
		for form_field, env_key in self.ENV_MAP.items():
			if form_field in self.SECRET_FIELDS:
				continue
			value = os.getenv(env_key, "")
			if form_field == "email_use_tls":
				initial[form_field] = str(value).lower() in {"1", "true", "yes", "on"}
			elif form_field == "email_port":
				initial[form_field] = int(value) if str(value).strip().isdigit() else None
			else:
				initial[form_field] = value
		form = OperationalSettingsForm(initial=initial)
		return render(request, self.template_name, {"form": form})

	def post(self, request):
		form = OperationalSettingsForm(request.POST)
		if form.is_valid():
			action = (request.POST.get("action") or "save").strip().lower()
			self._persist_settings(form)
			if action == "test-godaddy":
				self._run_godaddy_connection_test(request)
			else:
				messages.success(request, "Operational settings saved to environment variables.")
			return HttpResponseRedirect(reverse("dashboards:operational-settings"))
		return render(request, self.template_name, {"form": form})

	def _persist_settings(self, form: OperationalSettingsForm) -> None:
		env_path = settings.BASE_DIR / ".env"
		for form_field, env_key in self.ENV_MAP.items():
			value = form.cleaned_data.get(form_field)
			if form_field in self.SECRET_FIELDS and (value is None or str(value).strip() == ""):
				continue
			if form_field == "email_use_tls":
				value = "true" if bool(value) else "false"
			if value is None:
				value = ""
			value = str(value)
			set_key(str(env_path), env_key, value)
			os.environ[env_key] = value

		OperationalSettings.objects.all().delete()

	def _run_godaddy_connection_test(self, request) -> None:
		try:
			gateway = get_payment_gateway("godaddy")
			tester = getattr(gateway, "test_connection", None)
			if not callable(tester):
				messages.error(request, "GoDaddy connection test is not supported by the current gateway.")
				return
			result = tester(actor=request.user, request=request)
			status = (result or {}).get("status", "ok")
			messages.success(request, f"GoDaddy connection test passed (status: {status}).")
		except Exception as exc:
			messages.error(request, f"GoDaddy connection test failed: {exc}")
