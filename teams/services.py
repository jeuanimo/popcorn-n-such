from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum

from core.mail import send_runtime_mail
from orders.models import Order, OrderStatus

from .models import Team, TeamMembership, TeamMemberRole, TeamReminderLog

from sharing.services import ShareLinkService


class TeamService:
    ORDER_STATUSES_FOR_METRICS = (
        OrderStatus.PLACED,
        OrderStatus.PAID,
        OrderStatus.FULFILLING,
        OrderStatus.SHIPPED,
    )

    @staticmethod
    def generate_invite_code() -> str:
        code = uuid.uuid4().hex
        while Team.objects.filter(invite_code=code).exists():
            code = uuid.uuid4().hex
        return code

    @classmethod
    def create_team(cls, *, user, organization, form) -> Team:
        """Create a team. Sets the captain to *user* and creates a captain membership."""
        team = form.save(commit=False)
        team.captain = user
        team.organization = organization
        if not team.invite_code:
            team.invite_code = cls.generate_invite_code()
        team.save()

        # Auto-populate the public team link after PK is known
        base_url = getattr(settings, "SITE_BASE_URL", "http://localhost:8000")
        team.public_team_link = f"{base_url}/teams/{team.slug}/"
        team.save(update_fields=["public_team_link"])

        # Ensure the captain is in the membership list
        TeamMembership.objects.get_or_create(
            team=team,
            member=user,
            defaults={"role": TeamMemberRole.CAPTAIN, "is_active": True},
        )
        return team

    @classmethod
    def join_team_by_code(cls, *, user, invite_code: str) -> TeamMembership:
        try:
            team = Team.objects.get(invite_code=invite_code, is_active=True)
        except Team.DoesNotExist:
            raise ValidationError("Invalid or inactive invite code.")

        membership, created = TeamMembership.objects.get_or_create(
            team=team,
            member=user,
            defaults={"role": TeamMemberRole.MEMBER, "is_active": True},
        )
        if not created:
            if not membership.is_active:
                membership.is_active = True
                membership.save(update_fields=["is_active"])
            else:
                raise ValidationError("You are already a member of this team.")
        return membership

    @classmethod
    def dashboard_metrics(cls, *, team: Team) -> dict:
        orders = Order.objects.filter(team=team, status__in=cls.ORDER_STATUSES_FOR_METRICS)

        total_sales = int(orders.aggregate(total=Sum("total_cents")).get("total") or 0)
        total_orders = orders.count()

        goal_cents = int(Decimal(str(team.team_goal)) * 100)
        goal_progress_percent = (
            min(100, round((total_sales / goal_cents) * 100)) if goal_cents > 0 else 0
        )

        # Member-level breakdown: group by seller_link on the order and map back to member
        member_breakdown = (
            orders.filter(seller__seller__team_memberships__team=team)
            .values(
                "seller__seller__id",
                "seller__seller__username",
                "seller__seller__first_name",
                "seller__seller__last_name",
            )
            .annotate(order_count=Count("id"), sales_cents=Sum("total_cents"))
            .order_by("-sales_cents")
        )

        leaderboard = list(member_breakdown[:10])

        recent_orders = orders.select_related("customer", "seller").order_by("-created_at")[:10]

        share_obj = ShareLinkService.get_or_create_team_link(team=team, created_by=team.captain)
        share_link = ShareLinkService.build_public_url(share_obj.token)
        qr_data_uri = ShareLinkService.qr_data_uri_for_link(share_obj)
        qr_download_url = f"{share_link}qr.png"
        suggested_message = (
            f"Support {team.name}'s fundraiser! "
            f"Shop using this link: {share_link}"
        )

        return {
            "total_sales_cents": total_sales,
            "total_orders": total_orders,
            "goal_cents": goal_cents,
            "goal_progress_percent": goal_progress_percent,
            "member_breakdown": member_breakdown,
            "leaderboard": leaderboard,
            "recent_orders": recent_orders,
            "share_link": share_link,
            "qr_data_uri": qr_data_uri,
            "qr_download_url": qr_download_url,
            "suggested_message": suggested_message,
        }

    @classmethod
    def send_member_reminders(
        cls,
        *,
        team: Team,
        captain,
        subject: str,
        message: str,
        memberships=None,
    ) -> int:
        """Send reminder emails to team members and log them.

        *memberships* is an optional queryset/list of TeamMembership instances
        to target; if None, all active non-captain members are used.
        """
        if team.captain_id != captain.id:
            raise PermissionDenied("Only the team captain can send reminders.")

        if memberships is None:
            targets = TeamMembership.objects.filter(
                team=team,
                is_active=True,
            ).exclude(member=captain).select_related("member")
        else:
            targets = list(memberships)

        sent = 0
        for membership in targets:
            recipient = membership.member
            email = getattr(recipient, "email", None)
            if email:
                send_runtime_mail(
                    subject=subject,
                    message=message,
                    recipient_list=[email],
                    fail_silently=True,
                )
                TeamReminderLog.objects.create(
                    team=team,
                    sent_by=captain,
                    recipient=recipient,
                    message=f"Subject: {subject}\n\n{message}",
                )
                sent += 1
        return sent

    @classmethod
    def move_seller(cls, *, seller_link, from_team: Team, to_team: Team, staff_user) -> None:
        """Move a seller link from one team to another within the same campaign."""
        if not (staff_user.is_staff or staff_user.is_superuser or staff_user.has_any_role("staff", "admin")):
            raise PermissionDenied("Only staff can move sellers between teams.")

        # Both teams must share a campaign
        if from_team.campaign_id is None or from_team.campaign_id != to_team.campaign_id:
            raise ValidationError("Source and destination teams must share the same fundraiser campaign.")

        campaign = from_team.campaign

        # Validate seller is on the from_team's campaign
        if not campaign.sellers.filter(id=seller_link.id).exists():
            raise ValidationError("This seller is not attached to the campaign.")

        # Update any unresolved orders from old team to new team
        Order.objects.filter(
            team=from_team,
            seller__seller=seller_link.user,
            status__in=(OrderStatus.DRAFT, OrderStatus.PLACED),
        ).update(team=to_team)
