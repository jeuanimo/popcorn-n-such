from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from core.security import OrganizationManagerQuerysetMixin, RoleRequiredMixin
from fundraisers.models import FundraiserCampaign
from orders.models import Order, OrderStatus

from organizations.models import Organization
from organizations.services import convert_lead_to_campaign


def _money(cents: int) -> str:
    return f"${Decimal(int(cents)) / 100:.2f}"


class OrganizationCRMListView(RoleRequiredMixin, OrganizationManagerQuerysetMixin, View):
    allowed_roles = ("staff", "admin", "organization_manager")
    template_name = "organizations/crm_list.html"

    def get(self, request):
        organizations = self.get_queryset().order_by("name")
        return render(request, self.template_name, {"organizations": organizations})

    def get_queryset(self):
        return Organization.objects.all()


class OrganizationCRMDetailView(RoleRequiredMixin, OrganizationManagerQuerysetMixin, View):
    allowed_roles = ("staff", "admin", "organization_manager")
    template_name = "organizations/crm_detail.html"

    def get_queryset(self):
        return Organization.objects.all()

    def get(self, request, organization_id: int):
        org = get_object_or_404(self.get_queryset(), id=organization_id)

        campaigns = FundraiserCampaign.objects.filter(organization=org).order_by("-start_date")[:50]
        orders = (
            Order.objects.filter(fundraiser_campaign__organization=org, status__in=[OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.PROCESSING, OrderStatus.PACKED])
            .order_by("-created_at")
            .prefetch_related("items")[:50]
        )
        total_sales_cents = int(
            Order.objects.filter(fundraiser_campaign__organization=org).aggregate(total=Sum("total_cents")).get("total") or 0
        )

        return render(
            request,
            self.template_name,
            {
                "organization": org,
                "campaigns": campaigns,
                "orders": orders,
                "computed_total_sales": _money(total_sales_cents),
                "tasks": org.crm_tasks.select_related("assigned_to").all()[:50],
                "notes": org.crm_notes.select_related("created_by").all()[:50],
                "documents": org.documents.select_related("uploaded_by").all()[:20],
            },
        )


class ConvertOrganizationLeadView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, organization_id: int):
        org = get_object_or_404(Organization, id=organization_id)
        campaign = convert_lead_to_campaign(organization=org, actor=request.user, request=request)
        return HttpResponseRedirect(reverse("admin:fundraisers_fundraisercampaign_change", args=[campaign.id]))

