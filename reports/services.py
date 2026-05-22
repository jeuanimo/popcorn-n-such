from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from orders.models import Order, OrderItem, OrderStatus
from products.models import SKU
from purchase_orders.models import PurchaseOrder, PurchaseOrderStatus
from shipping.models import ShippingLabel
from supplies.models import Supply


REVENUE_STATUSES = (
    OrderStatus.PAID,
    OrderStatus.PROCESSING,
    OrderStatus.PACKED,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
)


def _range_to_datetimes(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.get_current_timezone())
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.get_current_timezone())
    return start_dt, end_dt


@dataclass(frozen=True)
class TabularReport:
    key: str
    title: str
    columns: list[str]
    rows: list[dict]


class ReportService:
    @staticmethod
    def _orders_in_range(*, start: date, end: date):
        start_dt, end_dt = _range_to_datetimes(start, end)
        return Order.objects.filter(
            created_at__gte=start_dt,
            created_at__lte=end_dt,
            status__in=REVENUE_STATUSES,
        )

    # ------------------------------------------------------------------
    # Sales reports (Orders)
    # ------------------------------------------------------------------

    @classmethod
    def sales_by_date(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                order_count=Count("id"),
                total_sales_cents=Sum("total_cents"),
                tax_cents=Sum("tax_cents"),
                shipping_cents=Sum("shipping_cents"),
            )
            .order_by("day")
        )
        return TabularReport(
            key="sales_by_date",
            title="Sales by Date",
            columns=["day", "order_count", "total_sales_cents", "tax_cents", "shipping_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_product(cls, *, start: date, end: date, base_order_qs=None) -> TabularReport:
        orders = base_order_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            OrderItem.objects.filter(order__in=orders)
            .values("product_id", "product__name")
            .annotate(
                total_units=Sum("quantity"),
                total_sales_cents=Sum("line_total_cents"),
                order_count=Count("order_id", distinct=True),
            )
            .order_by("-total_sales_cents", "product__name")
        )
        return TabularReport(
            key="sales_by_product",
            title="Sales by Product",
            columns=["product_id", "product__name", "order_count", "total_units", "total_sales_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_sku(cls, *, start: date, end: date, base_order_qs=None) -> TabularReport:
        orders = base_order_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            OrderItem.objects.filter(order__in=orders)
            .values("sku_id", "sku__sku_code", "product_name_snapshot")
            .annotate(
                total_units=Sum("quantity"),
                total_sales_cents=Sum("line_total_cents"),
                order_count=Count("order_id", distinct=True),
            )
            .order_by("-total_sales_cents", "sku__sku_code")
        )
        return TabularReport(
            key="sales_by_sku",
            title="Sales by SKU",
            columns=["sku_id", "sku__sku_code", "product_name_snapshot", "order_count", "total_units", "total_sales_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_fundraiser(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.filter(fundraiser_campaign__isnull=False)
            .values("fundraiser_campaign_id", "fundraiser_campaign__campaign_name")
            .annotate(order_count=Count("id"), total_sales_cents=Sum("total_cents"))
            .order_by("-total_sales_cents", "fundraiser_campaign__campaign_name")
        )
        return TabularReport(
            key="sales_by_fundraiser",
            title="Sales by Fundraiser",
            columns=["fundraiser_campaign_id", "fundraiser_campaign__campaign_name", "order_count", "total_sales_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_team(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.filter(team__isnull=False)
            .values("team_id", "team__name")
            .annotate(order_count=Count("id"), total_sales_cents=Sum("total_cents"))
            .order_by("-total_sales_cents", "team__name")
        )
        return TabularReport(
            key="sales_by_team",
            title="Sales by Team",
            columns=["team_id", "team__name", "order_count", "total_sales_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_seller(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.filter(seller__isnull=False)
            .values("seller_id", "seller__display_name", "seller__slug")
            .annotate(order_count=Count("id"), total_sales_cents=Sum("total_cents"))
            .order_by("-total_sales_cents", "seller__display_name")
        )
        return TabularReport(
            key="sales_by_seller",
            title="Sales by Seller",
            columns=["seller_id", "seller__display_name", "seller__slug", "order_count", "total_sales_cents"],
            rows=list(rows),
        )

    @classmethod
    def sales_by_organization(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.filter(fundraiser_campaign__organization__isnull=False)
            .values("fundraiser_campaign__organization_id", "fundraiser_campaign__organization__name")
            .annotate(order_count=Count("id"), total_sales_cents=Sum("total_cents"))
            .order_by("-total_sales_cents", "fundraiser_campaign__organization__name")
        )
        return TabularReport(
            key="sales_by_organization",
            title="Sales by Organization (Fundraisers)",
            columns=[
                "fundraiser_campaign__organization_id",
                "fundraiser_campaign__organization__name",
                "order_count",
                "total_sales_cents",
            ],
            rows=list(rows),
        )

    @classmethod
    def sales_by_channel(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        fundraiser = orders.filter(fundraiser_campaign__isnull=False).aggregate(
            order_count=Count("id"), total_sales_cents=Sum("total_cents")
        )
        direct = orders.filter(fundraiser_campaign__isnull=True).aggregate(
            order_count=Count("id"), total_sales_cents=Sum("total_cents")
        )
        rows = [
            {"channel": "fundraiser", **fundraiser},
            {"channel": "direct", **direct},
        ]
        for r in rows:
            r["order_count"] = r["order_count"] or 0
            r["total_sales_cents"] = r["total_sales_cents"] or 0
        return TabularReport(
            key="sales_by_channel",
            title="Sales by Channel",
            columns=["channel", "order_count", "total_sales_cents"],
            rows=rows,
        )

    # ------------------------------------------------------------------
    # Finance-ish reports
    # ------------------------------------------------------------------

    @classmethod
    def tax_report(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.values("shipping_state")
            .annotate(order_count=Count("id"), tax_cents=Sum("tax_cents"), taxable_sales_cents=Sum("subtotal_cents"))
            .order_by("-tax_cents", "shipping_state")
        )
        return TabularReport(
            key="tax_report",
            title="Tax Report (by shipping state)",
            columns=["shipping_state", "order_count", "taxable_sales_cents", "tax_cents"],
            rows=list(rows),
        )

    @classmethod
    def shipping_report(cls, *, start: date, end: date, base_order_qs=None) -> TabularReport:
        orders = base_order_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            ShippingLabel.objects.filter(order__in=orders, is_voided=False)
            .values("provider", "carrier", "service_name")
            .annotate(label_count=Count("id"), total_rate_cents=Sum("rate_cents"))
            .order_by("-label_count", "provider", "carrier", "service_name")
        )
        return TabularReport(
            key="shipping_report",
            title="Shipping Report (labels created)",
            columns=["provider", "carrier", "service_name", "label_count", "total_rate_cents"],
            rows=list(rows),
        )

    # ------------------------------------------------------------------
    # Inventory / supplies
    # ------------------------------------------------------------------

    @staticmethod
    def inventory_report() -> TabularReport:
        rows = (
            SKU.objects.select_related("product")
            .values("id", "sku_code", "product__name", "inventory_quantity", "low_stock_threshold", "is_active")
            .order_by("product__name", "sku_code")
        )
        return TabularReport(
            key="inventory_report",
            title="Inventory Report (SKUs)",
            columns=["id", "sku_code", "product__name", "inventory_quantity", "low_stock_threshold", "is_active"],
            rows=list(rows),
        )

    @staticmethod
    def supply_report() -> TabularReport:
        rows = (
            Supply.objects.values(
                "id",
                "name",
                "sku_code",
                "category",
                "unit",
                "inventory_quantity",
                "low_stock_threshold",
                "is_active",
            ).order_by("category", "name")
        )
        return TabularReport(
            key="supply_report",
            title="Supply Report",
            columns=[
                "id",
                "name",
                "sku_code",
                "category",
                "unit",
                "inventory_quantity",
                "low_stock_threshold",
                "is_active",
            ],
            rows=list(rows),
        )

    @staticmethod
    def low_stock_report() -> TabularReport:
        sku_rows = (
            SKU.objects.low_stock()
            .select_related("product")
            .values("sku_code", "product__name", "inventory_quantity", "low_stock_threshold")
            .order_by("product__name", "sku_code")
        )
        supply_rows = (
            Supply.objects.filter(is_active=True, inventory_quantity__lte=F("low_stock_threshold"))
            .values("name", "sku_code", "category", "inventory_quantity", "low_stock_threshold", "unit")
            .order_by("category", "name")
        )
        rows = [
            {
                "type": "sku",
                "name": r["product__name"],
                "code": r["sku_code"],
                "qty": r["inventory_quantity"],
                "threshold": r["low_stock_threshold"],
                "unit": "each",
            }
            for r in sku_rows
        ] + [
            {
                "type": "supply",
                "name": r["name"],
                "code": r["sku_code"],
                "qty": str(r["inventory_quantity"]),
                "threshold": str(r["low_stock_threshold"]),
                "unit": r["unit"],
            }
            for r in supply_rows
        ]
        return TabularReport(
            key="low_stock_report",
            title="Low Stock Report",
            columns=["type", "name", "code", "qty", "threshold", "unit"],
            rows=rows,
        )

    # ------------------------------------------------------------------
    # Customer / supplier reports (safe, aggregate)
    # ------------------------------------------------------------------

    @staticmethod
    def customer_report(*, start: date, end: date) -> TabularReport:
        start_dt, end_dt = _range_to_datetimes(start, end)
        # Avoid exposing private customer data: aggregate only.
        from django.contrib.auth import get_user_model

        User = get_user_model()
        total_customers = User.objects.count()
        new_customers = User.objects.filter(date_joined__gte=start_dt, date_joined__lte=end_dt).count()
        rows = [
            {"metric": "total_customers", "value": total_customers},
            {"metric": "new_customers_in_range", "value": new_customers},
        ]
        return TabularReport(
            key="customer_report",
            title="Customer Report (aggregate)",
            columns=["metric", "value"],
            rows=rows,
        )

    @staticmethod
    def supplier_purchase_report(*, start: date, end: date) -> TabularReport:
        start_dt, end_dt = _range_to_datetimes(start, end)
        rows = (
            PurchaseOrder.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)
            .exclude(status=PurchaseOrderStatus.CANCELED)
            .values("supplier_id", "supplier__name")
            .annotate(po_count=Count("id"), total_cents=Sum("total_cents"))
            .order_by("-total_cents", "supplier__name")
        )
        return TabularReport(
            key="supplier_purchase_report",
            title="Supplier Purchase Report",
            columns=["supplier_id", "supplier__name", "po_count", "total_cents"],
            rows=list(rows),
        )

    @classmethod
    def fundraiser_payout_estimate(cls, *, start: date, end: date, base_qs=None) -> TabularReport:
        orders = base_qs or cls._orders_in_range(start=start, end=end)
        rows = (
            orders.filter(fundraiser_campaign__isnull=False)
            .values(
                "fundraiser_campaign_id",
                "fundraiser_campaign__campaign_name",
                "fundraiser_campaign__profit_percentage",
            )
            .annotate(total_sales_cents=Sum("total_cents"), order_count=Count("id"))
            .order_by("-total_sales_cents", "fundraiser_campaign__campaign_name")
        )
        out = []
        for r in rows:
            pct = r["fundraiser_campaign__profit_percentage"] or 0
            payout_cents = int((r["total_sales_cents"] or 0) * (float(pct) / 100.0))
            out.append(
                {
                    "fundraiser_campaign_id": r["fundraiser_campaign_id"],
                    "fundraiser_campaign__campaign_name": r["fundraiser_campaign__campaign_name"],
                    "profit_percentage": str(pct),
                    "order_count": r["order_count"] or 0,
                    "total_sales_cents": r["total_sales_cents"] or 0,
                    "payout_estimate_cents": payout_cents,
                }
            )
        return TabularReport(
            key="fundraiser_payout_estimate",
            title="Fundraiser Payout Estimate",
            columns=[
                "fundraiser_campaign_id",
                "fundraiser_campaign__campaign_name",
                "profit_percentage",
                "order_count",
                "total_sales_cents",
                "payout_estimate_cents",
            ],
            rows=out,
        )

