from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from orders.models import Order, OrderItem, OrderStatus

from .models import LeaderboardScope, LeaderboardSettings, LeaderboardSnapshot

# Only fully-paid/fulfilling/shipped orders count.
_PAID_STATUSES = (
    OrderStatus.PAID,
    OrderStatus.FULFILLING,
    OrderStatus.SHIPPED,
)


def _goal_pct(sales_cents: int, goal_cents: int) -> int:
    if goal_cents <= 0:
        return 0
    return min(100, round((sales_cents / goal_cents) * 100))


class LeaderboardService:

    # ------------------------------------------------------------------
    # Public read methods (always return live data from DB)
    # ------------------------------------------------------------------

    @staticmethod
    def top_sellers_in_campaign(campaign, *, limit: int = 20) -> list[dict]:
        """
        Top seller stores by total sales for a given campaign.
        Returns public-safe data (display_name only).
        """
        rows = (
            Order.objects.filter(fundraiser_campaign=campaign, status__in=_PAID_STATUSES, seller__isnull=False)
            .values(
                "seller_id",
                "seller__display_name",
                "seller__seller_goal",
            )
            .annotate(
                total_sales=Sum("total_cents"),
                total_orders=Count("id"),
            )
            .order_by("-total_sales")[:limit]
        )
        results = []
        for rank, row in enumerate(rows, start=1):
            goal_cents = int(Decimal(str(row["seller__seller_goal"] or 0)) * 100)
            results.append({
                "rank": rank,
                "seller_store_id": row["seller_id"],
                "display_name": row["seller__display_name"],
                "total_sales_cents": row["total_sales"] or 0,
                "total_orders": row["total_orders"] or 0,
                "goal_cents": goal_cents,
                "goal_progress_percent": _goal_pct(row["total_sales"] or 0, goal_cents),
            })
        return results

    @staticmethod
    def top_teams_in_campaign(campaign, *, limit: int = 20) -> list[dict]:
        """Top teams by total sales for a given campaign."""
        rows = (
            Order.objects.filter(fundraiser_campaign=campaign, status__in=_PAID_STATUSES, team__isnull=False)
            .values("team_id", "team__name", "team__team_goal")
            .annotate(
                total_sales=Sum("total_cents"),
                total_orders=Count("id"),
            )
            .order_by("-total_sales")[:limit]
        )
        results = []
        for rank, row in enumerate(rows, start=1):
            goal_cents = int(Decimal(str(row["team__team_goal"] or 0)) * 100)
            results.append({
                "rank": rank,
                "team_id": row["team_id"],
                "display_name": row["team__name"],
                "total_sales_cents": row["total_sales"] or 0,
                "total_orders": row["total_orders"] or 0,
                "goal_cents": goal_cents,
                "goal_progress_percent": _goal_pct(row["total_sales"] or 0, goal_cents),
            })
        return results

    @staticmethod
    def top_sellers_in_team(team, *, limit: int = 20) -> list[dict]:
        """
        Top sellers within a specific team.
        Uses display_name (no private info) for public views.
        Full name is included for captain/staff views.
        """
        rows = (
            Order.objects.filter(team=team, status__in=_PAID_STATUSES, seller__isnull=False)
            .values(
                "seller_id",
                "seller__display_name",
                "seller__seller_goal",
                "seller__seller__first_name",
                "seller__seller__last_name",
                "seller__seller__username",
            )
            .annotate(
                total_sales=Sum("total_cents"),
                total_orders=Count("id"),
            )
            .order_by("-total_sales")[:limit]
        )
        results = []
        for rank, row in enumerate(rows, start=1):
            goal_cents = int(Decimal(str(row["seller__seller_goal"] or 0)) * 100)
            fn = row["seller__seller__first_name"] or ""
            ln = row["seller__seller__last_name"] or ""
            full_name = f"{fn} {ln}".strip() or row["seller__seller__username"]
            results.append({
                "rank": rank,
                "seller_store_id": row["seller_id"],
                "display_name": row["seller__display_name"],
                "full_name": full_name,  # Only expose in privileged views
                "total_sales_cents": row["total_sales"] or 0,
                "total_orders": row["total_orders"] or 0,
                "goal_cents": goal_cents,
                "goal_progress_percent": _goal_pct(row["total_sales"] or 0, goal_cents),
            })
        return results

    @staticmethod
    def top_campaigns(*, limit: int = 20) -> list[dict]:
        """Staff-only: top campaigns by total sales."""
        rows = (
            Order.objects.filter(status__in=_PAID_STATUSES, fundraiser_campaign__isnull=False)
            .values("fundraiser_campaign_id", "fundraiser_campaign__campaign_name", "fundraiser_campaign__goal_amount")
            .annotate(
                total_sales=Sum("total_cents"),
                total_orders=Count("id"),
            )
            .order_by("-total_sales")[:limit]
        )
        results = []
        for rank, row in enumerate(rows, start=1):
            goal_cents = int(Decimal(str(row["fundraiser_campaign__goal_amount"] or 0)) * 100)
            results.append({
                "rank": rank,
                "campaign_id": row["fundraiser_campaign_id"],
                "display_name": row["fundraiser_campaign__campaign_name"],
                "total_sales_cents": row["total_sales"] or 0,
                "total_orders": row["total_orders"] or 0,
                "goal_cents": goal_cents,
                "goal_progress_percent": _goal_pct(row["total_sales"] or 0, goal_cents),
            })
        return results

    @staticmethod
    def units_sold_in_campaign(campaign) -> dict:
        """Total units sold across all orders in a campaign (paid only)."""
        result = (
            OrderItem.objects.filter(
                order__fundraiser_campaign=campaign,
                order__status__in=_PAID_STATUSES,
            )
            .aggregate(total_units=Sum("quantity"))
        )
        return {"total_units": result["total_units"] or 0}

    # ------------------------------------------------------------------
    # Snapshot persistence (cache for fast dashboard reads)
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def refresh_campaign_snapshots(cls, campaign) -> None:
        """
        Recompute and persist LeaderboardSnapshot rows for a campaign.
        Called after order status changes.
        """
        # -- Top sellers --
        LeaderboardSnapshot.objects.filter(
            scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=campaign
        ).delete()
        for row in cls.top_sellers_in_campaign(campaign, limit=50):
            from sellers.models import SellerStore  # avoid circular at module level
            try:
                store = SellerStore.objects.get(pk=row["seller_store_id"])
            except SellerStore.DoesNotExist:
                continue
            LeaderboardSnapshot.objects.create(
                scope=LeaderboardScope.CAMPAIGN_SELLERS,
                campaign=campaign,
                seller_store=store,
                display_name=row["display_name"],
                rank=row["rank"],
                total_sales_cents=row["total_sales_cents"],
                total_orders=row["total_orders"],
                goal_cents=row["goal_cents"],
                goal_progress_percent=row["goal_progress_percent"],
            )

        # -- Top teams --
        LeaderboardSnapshot.objects.filter(
            scope=LeaderboardScope.CAMPAIGN_TEAMS, campaign=campaign
        ).delete()
        for row in cls.top_teams_in_campaign(campaign, limit=50):
            from teams.models import Team
            try:
                team_obj = Team.objects.get(pk=row["team_id"])
            except Team.DoesNotExist:
                continue
            LeaderboardSnapshot.objects.create(
                scope=LeaderboardScope.CAMPAIGN_TEAMS,
                campaign=campaign,
                ranked_team=team_obj,
                display_name=row["display_name"],
                rank=row["rank"],
                total_sales_cents=row["total_sales_cents"],
                total_orders=row["total_orders"],
                goal_cents=row["goal_cents"],
                goal_progress_percent=row["goal_progress_percent"],
            )

    @classmethod
    @transaction.atomic
    def refresh_team_snapshots(cls, team) -> None:
        """Recompute seller-within-team snapshots."""
        LeaderboardSnapshot.objects.filter(
            scope=LeaderboardScope.TEAM_SELLERS, team=team
        ).delete()
        for row in cls.top_sellers_in_team(team, limit=50):
            from sellers.models import SellerStore
            try:
                store = SellerStore.objects.get(pk=row["seller_store_id"])
            except SellerStore.DoesNotExist:
                continue
            LeaderboardSnapshot.objects.create(
                scope=LeaderboardScope.TEAM_SELLERS,
                team=team,
                seller_store=store,
                display_name=row["display_name"],
                rank=row["rank"],
                total_sales_cents=row["total_sales_cents"],
                total_orders=row["total_orders"],
                goal_cents=row["goal_cents"],
                goal_progress_percent=row["goal_progress_percent"],
            )

    @classmethod
    @transaction.atomic
    def refresh_all_campaign_snapshots(cls) -> None:
        """Staff view: refresh the all-campaigns snapshot."""
        LeaderboardSnapshot.objects.filter(scope=LeaderboardScope.ALL_CAMPAIGNS).delete()
        for row in cls.top_campaigns(limit=100):
            from fundraisers.models import FundraiserCampaign
            try:
                campaign_obj = FundraiserCampaign.objects.get(pk=row["campaign_id"])
            except FundraiserCampaign.DoesNotExist:
                continue
            LeaderboardSnapshot.objects.create(
                scope=LeaderboardScope.ALL_CAMPAIGNS,
                ranked_campaign=campaign_obj,
                display_name=row["display_name"],
                rank=row["rank"],
                total_sales_cents=row["total_sales_cents"],
                total_orders=row["total_orders"],
                goal_cents=row["goal_cents"],
                goal_progress_percent=row["goal_progress_percent"],
            )

    # ------------------------------------------------------------------
    # Visibility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_settings(campaign) -> LeaderboardSettings:
        settings_obj, _ = LeaderboardSettings.objects.get_or_create(campaign=campaign)
        return settings_obj
