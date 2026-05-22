from __future__ import annotations

from dataclasses import asdict

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from django.views import View

from core.security import RoleRequiredMixin
from fundraisers.models import FundraiserCampaign
from orders.models import Order
from security_audit.utils import log_audit_event
from teams.models import Team

from .forms import DateRangeForm
from .models import ReportExportLog, ReportFormat
from .services import ReportService, TabularReport
from .utils import tabular_to_csv_response


class _BaseReportView(RoleRequiredMixin, View):
    allowed_roles: tuple[str, ...] = ("staff", "admin")
    report_key: str = ""

    def get_date_range(self, request: HttpRequest):
        form = DateRangeForm(request.GET)
        start, end = form.cleaned_range()
        return form, start, end

    def render_report(self, request: HttpRequest, report: TabularReport, form: DateRangeForm) -> HttpResponse:
        return render(
            request,
            "reports/report_table.html",
            {
                "report": report,
                "columns": report.columns,
                "rows": report.rows,
                "form": form,
            },
        )

    def export_report_csv(self, request: HttpRequest, report: TabularReport, *, start, end) -> HttpResponse:
        params = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        ReportExportLog.objects.create(
            report_key=report.key,
            report_format=ReportFormat.CSV,
            parameters=params,
            row_count=len(report.rows),
            exported_by=request.user if request.user.is_authenticated else None,
            ip_address=(request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        )
        log_audit_event(
            action="report_export",
            message=f"Exported report {report.key} as CSV",
            actor=request.user if request.user.is_authenticated else None,
            request=request,
            metadata={"report_key": report.key, "format": "csv", **params},
        )
        filename = f"{slugify(report.key)}_{start.isoformat()}_{end.isoformat()}.csv"
        return tabular_to_csv_response(filename=filename, columns=report.columns, rows=report.rows)

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        raise NotImplementedError


class ReportsDashboardView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "reports/dashboard.html")


class MyReportsDashboardView(RoleRequiredMixin, View):
    allowed_roles = ("organization_manager", "team_captain", "staff", "admin")

    def get(self, request: HttpRequest) -> HttpResponse:
        campaigns = FundraiserCampaign.objects.none()
        teams = Team.objects.none()
        if request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin"):
            campaigns = FundraiserCampaign.objects.all().order_by("-start_date")[:50]
            teams = Team.objects.all().order_by("name")[:50]
        else:
            if request.user.has_any_role("organization_manager"):
                campaigns = FundraiserCampaign.objects.filter(organization__manager=request.user).order_by("-start_date")
            if request.user.has_any_role("team_captain"):
                teams = Team.objects.filter(captain=request.user).order_by("name")
        return render(request, "reports/my_dashboard.html", {"campaigns": campaigns, "teams": teams})


class MyFundraiserReportView(RoleRequiredMixin, View):
    allowed_roles = ("organization_manager", "staff", "admin")

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        campaign = get_object_or_404(FundraiserCampaign, slug=slug)
        if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
            if campaign.organization.manager_id != request.user.id:
                raise PermissionDenied("You can only export reports for your organization.")

        form, start, end = DateRangeForm(request.GET), None, None
        start, end = form.cleaned_range()
        base_qs = Order.objects.filter(fundraiser_campaign=campaign)
        report = ReportService.sales_by_date(start=start, end=end, base_qs=base_qs)
        # Make the report key specific for audit clarity
        report = TabularReport(
            key="campaign_sales_by_date",
            title=f"Campaign Sales by Date — {campaign.campaign_name}",
            columns=report.columns,
            rows=report.rows,
        )

        if request.GET.get("format") == "csv":
            return _BaseReportView().export_report_csv(request, report, start=start, end=end)
        return render(
            request,
            "reports/report_table.html",
            {"report": report, "columns": report.columns, "rows": report.rows, "form": form},
        )


class MyTeamReportView(RoleRequiredMixin, View):
    allowed_roles = ("team_captain", "staff", "admin")

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        team = get_object_or_404(Team, slug=slug)
        if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
            if team.captain_id != request.user.id:
                raise PermissionDenied("You can only export reports for your team.")

        form = DateRangeForm(request.GET)
        start, end = form.cleaned_range()
        base_qs = Order.objects.filter(team=team)
        report = ReportService.sales_by_date(start=start, end=end, base_qs=base_qs)
        report = TabularReport(
            key="team_sales_by_date",
            title=f"Team Sales by Date — {team.name}",
            columns=report.columns,
            rows=report.rows,
        )
        if request.GET.get("format") == "csv":
            return _BaseReportView().export_report_csv(request, report, start=start, end=end)
        return render(
            request,
            "reports/report_table.html",
            {"report": report, "columns": report.columns, "rows": report.rows, "form": form},
        )


# ---------------------------------------------------------------------------
# Staff report views
# ---------------------------------------------------------------------------


class SalesByDateReportView(_BaseReportView):
    report_key = "sales_by_date"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_date(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesByProductReportView(_BaseReportView):
    report_key = "sales_by_product"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_product(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesBySKUReportView(_BaseReportView):
    report_key = "sales_by_sku"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_sku(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesByFundraiserReportView(_BaseReportView):
    report_key = "sales_by_fundraiser"

    def get(self, request: HttpRequest, campaign_slug: str | None = None) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        base_qs = None
        if campaign_slug:
            campaign = get_object_or_404(FundraiserCampaign, slug=campaign_slug)
            base_qs = Order.objects.filter(fundraiser_campaign=campaign)
        report = ReportService.sales_by_fundraiser(start=start, end=end, base_qs=base_qs)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesByTeamReportView(_BaseReportView):
    report_key = "sales_by_team"

    def get(self, request: HttpRequest, team_slug: str | None = None) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        base_qs = None
        if team_slug:
            team = get_object_or_404(Team, slug=team_slug)
            base_qs = Order.objects.filter(team=team)
        report = ReportService.sales_by_team(start=start, end=end, base_qs=base_qs)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesBySellerReportView(_BaseReportView):
    report_key = "sales_by_seller"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_seller(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesByOrganizationReportView(_BaseReportView):
    report_key = "sales_by_organization"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_organization(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SalesByChannelReportView(_BaseReportView):
    report_key = "sales_by_channel"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.sales_by_channel(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class TaxReportView(_BaseReportView):
    report_key = "tax_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.tax_report(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class ShippingReportView(_BaseReportView):
    report_key = "shipping_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.shipping_report(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class InventoryReportView(_BaseReportView):
    report_key = "inventory_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = DateRangeForm(request.GET)  # not used, but keeps template consistent
        report = ReportService.inventory_report()
        if request.GET.get("format") == "csv":
            # Keep filename stable; date range not applicable.
            start, end = form.cleaned_range()
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SupplyReportView(_BaseReportView):
    report_key = "supply_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = DateRangeForm(request.GET)
        report = ReportService.supply_report()
        if request.GET.get("format") == "csv":
            start, end = form.cleaned_range()
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class LowStockReportView(_BaseReportView):
    report_key = "low_stock_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = DateRangeForm(request.GET)
        report = ReportService.low_stock_report()
        if request.GET.get("format") == "csv":
            start, end = form.cleaned_range()
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class CustomerReportView(_BaseReportView):
    report_key = "customer_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.customer_report(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class SupplierPurchaseReportView(_BaseReportView):
    report_key = "supplier_purchase_report"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.supplier_purchase_report(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)


class FundraiserPayoutEstimateReportView(_BaseReportView):
    report_key = "fundraiser_payout_estimate"

    def get(self, request: HttpRequest) -> HttpResponse:
        form, start, end = self.get_date_range(request)
        report = ReportService.fundraiser_payout_estimate(start=start, end=end)
        if request.GET.get("format") == "csv":
            return self.export_report_csv(request, report, start=start, end=end)
        return self.render_report(request, report, form)
