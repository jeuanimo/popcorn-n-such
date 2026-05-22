"""
Signals for leaderboards: refresh snapshots whenever an order's status
changes to (or from) a paid state.
"""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from orders.models import Order, OrderStatus

_PAID_STATUSES = {
    OrderStatus.PAID,
    getattr(OrderStatus, "FULFILLING", None),
    getattr(OrderStatus, "PROCESSING", None),
    getattr(OrderStatus, "PACKED", None),
    getattr(OrderStatus, "SHIPPED", None),
    getattr(OrderStatus, "DELIVERED", None),
}
_PAID_STATUSES = {status for status in _PAID_STATUSES if status}


@receiver(post_save, sender=Order)
def refresh_leaderboard_on_order_save(sender, instance: Order, **kwargs):
    """
    After an order is saved, refresh all relevant leaderboard snapshots
    if the order is in a paid state and has campaign/team attribution.
    """
    if instance.status not in _PAID_STATUSES:
        return

    # Defer import to avoid circular at module level
    from leaderboards.services import LeaderboardService

    if instance.fundraiser_campaign_id:
        LeaderboardService.refresh_campaign_snapshots(instance.fundraiser_campaign)

    if instance.team_id:
        LeaderboardService.refresh_team_snapshots(instance.team)

    if not instance.fundraiser_campaign_id and not instance.team_id:
        # Edge case: standalone paid orders — refresh staff all-campaigns summary
        LeaderboardService.refresh_all_campaign_snapshots()
