from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.models import Count, F, Q, Sum

from orders.models import Order, OrderStatus
from products.models import Product

from .models import SellerStore

from sharing.services import ShareLinkService


_ORDER_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.PAID,
    OrderStatus.FULFILLING,
    OrderStatus.SHIPPED,
)


class SellerStoreService:
    @staticmethod
    def _annotate_stock_summary(qs):
        return qs.annotate(
            total_active_stock=Sum("skus__inventory_quantity", filter=Q(skus__is_active=True)),
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

    @staticmethod
    def build_public_link(store: SellerStore) -> str:
        base = getattr(settings, "SITE_BASE_URL", "http://localhost:8000")
        return f"{base}/store/{store.slug}/"

    @classmethod
    def create_or_update_store(cls, *, user, form) -> SellerStore:
        """
        Save a seller store form.  Sets the seller FK to *user* so the seller
        cannot set it to someone else.  Generates/refreshes the public link.
        """
        store = form.save(commit=False)
        store.seller = user  # server-authoritative — never from user input
        store.save()
        # Refresh public link now that we have a PK and slug
        store.public_seller_link = cls.build_public_link(store)
        store.save(update_fields=["public_seller_link"])
        return store

    @classmethod
    def dashboard_metrics(cls, *, store: SellerStore) -> dict:
        """Return metrics for the seller's personal dashboard."""
        orders = Order.objects.filter(
            seller=store,
            status__in=_ORDER_STATUSES,
        )

        total_sales = int(orders.aggregate(total=Sum("total_cents")).get("total") or 0)
        total_orders = orders.count()

        goal_cents = int(Decimal(str(store.seller_goal)) * 100)
        goal_progress_percent = (
            min(100, round((total_sales / goal_cents) * 100)) if goal_cents > 0 else 0
        )

        # Recent supporters (unique customers)
        recent_supporters = (
            orders.select_related("customer")
            .order_by("-created_at")
            .values("customer__id", "customer__first_name", "customer__last_name", "customer__username", "created_at", "total_cents")[:10]
        )

        # Leaderboard rank within the same campaign/team scope
        leaderboard_rank = None
        if store.campaign_id:
            ranks = (
                Order.objects.filter(
                    seller__campaign=store.campaign,
                    status__in=_ORDER_STATUSES,
                )
                .values("seller_id")
                .annotate(sales=Sum("total_cents"))
                .order_by("-sales")
            )
            for i, row in enumerate(ranks, start=1):
                if row["seller_id"] == store.pk:
                    leaderboard_rank = i
                    break

        share_obj = ShareLinkService.get_or_create_seller_link(store=store, created_by=store.seller)
        share_link = ShareLinkService.build_public_url(share_obj.token)
        qr_data_uri = ShareLinkService.qr_data_uri_for_link(share_obj)
        qr_download_url = f"{share_link}qr.png"

        seller_name = store.seller.get_full_name() or store.seller.get_username()
        suggested_message = (
            f"Support {seller_name}'s fundraiser! "
            f"Shop at {share_link} "
            f"and help reach the ${store.seller_goal:,.0f} goal."
        )

        return {
            "total_sales_cents": total_sales,
            "total_orders": total_orders,
            "goal_cents": goal_cents,
            "goal_progress_percent": goal_progress_percent,
            "recent_supporters": recent_supporters,
            "leaderboard_rank": leaderboard_rank,
            "share_link": share_link,
            "qr_data_uri": qr_data_uri,
            "qr_download_url": qr_download_url,
            "suggested_message": suggested_message,
        }

    @staticmethod
    def public_store_products(store: SellerStore):
        """Products eligible to be purchased through this store."""
        if store.campaign_id:
            # Campaign-scoped: only fundraiser-eligible products
            base = Product.objects.fundraiser_store()
        else:
            base = Product.objects.public_store()
        return SellerStoreService._annotate_stock_summary(
            base.select_related("category").prefetch_related("skus")
        )
