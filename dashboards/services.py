from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, F, Sum
from django.utils import timezone

from notifications.models import NotificationDeliveryChannel, NotificationDeliveryLog, NotificationEvent
from orders.models import Order, OrderItem, OrderStatus
from products.models import SKU
from shipping.models import AddressValidation, ShippingLabel, ShippingRate
from supplies.models import Supply


PAID_STATUSES = (
	OrderStatus.PAID,
	OrderStatus.PROCESSING,
	OrderStatus.PACKED,
	OrderStatus.SHIPPED,
	OrderStatus.DELIVERED,
)


def _money(cents: int) -> str:
	return f"${Decimal(int(cents)) / 100:.2f}"


class OwnerDashboardService:
	@staticmethod
	def context(*, user) -> dict:
		orders_paid = Order.objects.filter(status__in=PAID_STATUSES)
		total_revenue = int(orders_paid.aggregate(total=Sum("total_cents")).get("total") or 0)

		revenue_by_channel = {
			"standalone": int(orders_paid.filter(fundraiser_campaign__isnull=True).aggregate(total=Sum("total_cents")).get("total") or 0),
			"fundraisers": int(orders_paid.filter(fundraiser_campaign__isnull=False).aggregate(total=Sum("total_cents")).get("total") or 0),
		}

		active_fundraisers = Order.objects.filter(fundraiser_campaign__isnull=False).values("fundraiser_campaign_id").distinct().count()

		open_orders = Order.objects.exclude(status__in=[OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELED, OrderStatus.REFUNDED]).count()
		fulfillment_queue = Order.objects.filter(status__in=[OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PACKED]).count()

		low_inventory = SKU.objects.low_stock().select_related("product").order_by("product__name")[:10]
		low_supplies = Supply.objects.filter(is_active=True).order_by("name")
		low_supplies = [s for s in low_supplies if s.is_low_stock][:10]

		top_products = (
			OrderItem.objects.filter(order__status__in=PAID_STATUSES)
			.values("sku_id", "sku__sku_code", "product_name_snapshot")
			.annotate(units=Sum("quantity"), sales=Sum("line_total_cents"))
			.order_by("-sales")[:10]
		)
		top_fundraisers = (
			Order.objects.filter(status__in=PAID_STATUSES, fundraiser_campaign__isnull=False)
			.values("fundraiser_campaign_id", "fundraiser_campaign__campaign_name")
			.annotate(sales=Sum("total_cents"), orders=Count("id"))
			.order_by("-sales")[:10]
		)
		top_organizations = (
			Order.objects.filter(status__in=PAID_STATUSES, fundraiser_campaign__organization__isnull=False)
			.values("fundraiser_campaign__organization_id", "fundraiser_campaign__organization__name")
			.annotate(sales=Sum("total_cents"), orders=Count("id"))
			.order_by("-sales")[:10]
		)
		recent_orders = Order.objects.select_related("customer", "fundraiser_campaign", "team", "seller").order_by("-created_at")[:10]

		unread_alerts = NotificationDeliveryLog.objects.filter(
			user=user, channel=NotificationDeliveryChannel.INTERNAL, read_at__isnull=True
		).count()
		recent_alerts = NotificationEvent.objects.order_by("-created_at")[:10]

		return {
			"total_revenue": _money(total_revenue),
			"revenue_by_channel": {k: _money(v) for k, v in revenue_by_channel.items()},
			"active_fundraisers": active_fundraisers,
			"open_orders": open_orders,
			"fulfillment_queue": fulfillment_queue,
			"low_inventory": low_inventory,
			"low_supplies": low_supplies,
			"top_products": top_products,
			"top_fundraisers": top_fundraisers,
			"top_organizations": top_organizations,
			"recent_orders": recent_orders,
			"unread_alerts": unread_alerts,
			"recent_alerts": recent_alerts,
		}


class FulfillmentDashboardService:
	@staticmethod
	def context(*, user) -> dict:
		paid_waiting_ship = Order.objects.filter(status__in=[OrderStatus.PAID, OrderStatus.PROCESSING]).order_by("-created_at")[:50]
		labels_needed = Order.objects.filter(status__in=[OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PACKED]).exclude(
			shipping_labels__is_voided=False
		).order_by("-created_at")[:50]
		packed_orders = Order.objects.filter(status=OrderStatus.PACKED).order_by("-updated_at")[:50]
		shipped_orders = Order.objects.filter(status=OrderStatus.SHIPPED).order_by("-updated_at")[:50]
		address_problems = AddressValidation.objects.filter(is_valid=False).select_related("order").order_by("-validated_at")[:50]
		reprint_labels = ShippingLabel.objects.filter(is_voided=False, reprint_count__gt=0).select_related("order").order_by("-created_at")[:50]

		unread_alerts = NotificationDeliveryLog.objects.filter(
			user=user, channel=NotificationDeliveryChannel.INTERNAL, read_at__isnull=True
		).count()
		return {
			"paid_waiting_ship": paid_waiting_ship,
			"labels_needed": labels_needed,
			"packed_orders": packed_orders,
			"shipped_orders": shipped_orders,
			"address_problems": address_problems,
			"reprint_labels": reprint_labels,
			"unread_alerts": unread_alerts,
		}


class OrganizationDashboardService:
	@staticmethod
	def context(*, organization) -> dict:
		from fundraisers.services import FundraiserCampaignService
		campaigns = organization.fundraiser_campaigns.order_by("-start_date")
		active_campaigns = campaigns.filter(status="active", is_active=True)

		campaign_metrics = []
		for c in active_campaigns[:5]:
			campaign_metrics.append({"campaign": c, **FundraiserCampaignService.dashboard_metrics(campaign=c)})

		return {
			"organization": organization,
			"active_campaigns": active_campaigns[:10],
			"campaign_metrics": campaign_metrics,
		}


class TeamDashboardService:
	@staticmethod
	def context(*, team) -> dict:
		from teams.services import TeamService
		from leaderboards.services import LeaderboardService

		metrics = TeamService.dashboard_metrics(team=team)
		# Privileged team-captain view: seller leaderboard within team
		seller_leaderboard = LeaderboardService.top_sellers_in_team(team, limit=10)

		return {
			"team": team,
			**metrics,
			"seller_leaderboard": seller_leaderboard,
		}


class SellerDashboardService:
	@staticmethod
	def context(*, store) -> dict:
		from sellers.services import SellerStoreService
		return {"store": store, **SellerStoreService.dashboard_metrics(store=store)}


class CustomerDashboardService:
	@staticmethod
	def context(*, user, request=None) -> dict:
		from accounts.models import SavedAddress
		from cart.services import CartService

		orders = Order.objects.filter(customer=user).order_by("-created_at")[:25]
		addresses = SavedAddress.objects.filter(user=user).order_by("-is_default", "-updated_at")[:10]
		cart = CartService.get_or_create_cart(request) if request is not None else None

		return {
			"orders": orders,
			"addresses": addresses,
			"cart": cart,
		}

