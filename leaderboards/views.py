from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView

from fundraisers.models import FundraiserCampaign
from teams.models import Team
from core.security import RoleRequiredMixin

from .models import LeaderboardScope, LeaderboardSettings, LeaderboardSnapshot
from .services import LeaderboardService


def _is_staff_or_admin(user) -> bool:
	return (
		user.is_staff
		or user.is_superuser
		or (hasattr(user, "has_any_role") and user.has_any_role("staff", "admin"))
	)


# ---------------------------------------------------------------------------
# Public campaign leaderboard
# ---------------------------------------------------------------------------

def public_campaign_leaderboard_view(request, campaign_slug: str):
	"""
	Public-facing leaderboard for a campaign.
	Respects LeaderboardSettings visibility flags.
	Only shows display_name — no private customer data.
	"""
	campaign = get_object_or_404(FundraiserCampaign, slug=campaign_slug, is_active=True)
	lb_settings = LeaderboardService.get_settings(campaign)

	is_staff = request.user.is_authenticated and _is_staff_or_admin(request.user)

	sellers_visible = lb_settings.public_sellers_visible or is_staff
	teams_visible = lb_settings.public_teams_visible or is_staff

	top_sellers = (
		LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=campaign
		).order_by("rank")[:20]
		if sellers_visible else []
	)
	top_teams = (
		LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.CAMPAIGN_TEAMS, campaign=campaign
		).order_by("rank")[:20]
		if teams_visible else []
	)

	return render(request, "leaderboards/public_campaign.html", {
		"campaign": campaign,
		"lb_settings": lb_settings,
		"top_sellers": top_sellers,
		"top_teams": top_teams,
		"sellers_visible": sellers_visible,
		"teams_visible": teams_visible,
		"is_staff": is_staff,
	})


# ---------------------------------------------------------------------------
# Team internal leaderboard (captain / member / staff)
# ---------------------------------------------------------------------------

@login_required
def team_leaderboard_view(request, team_slug: str):
	"""
	Member performance within a team.
	Captains and staff see full names; plain members see display names only.
	"""
	team = get_object_or_404(Team, slug=team_slug, is_active=True)
	is_staff = _is_staff_or_admin(request.user)
	is_captain = team.captain_id == request.user.pk
	show_full_names = is_staff or is_captain

	# Non-members are still allowed to read the team leaderboard if the team is active
	rows = LeaderboardSnapshot.objects.filter(
		scope=LeaderboardScope.TEAM_SELLERS, team=team
	).order_by("rank")[:20]

	# Fall back to live data if snapshot is empty
	if not rows.exists():
		rows = LeaderboardService.top_sellers_in_team(team, limit=20)
		use_live = True
	else:
		use_live = False

	return render(request, "leaderboards/team_leaderboard.html", {
		"team": team,
		"rows": rows,
		"use_live": use_live,
		"show_full_names": show_full_names,
		"is_captain": is_captain,
		"is_staff": is_staff,
	})


# ---------------------------------------------------------------------------
# Staff: all-campaigns leaderboard
# ---------------------------------------------------------------------------

class StaffAllCampaignsLeaderboardView(RoleRequiredMixin, TemplateView):
	template_name = "leaderboards/staff_all_campaigns.html"
	allowed_roles = ("staff", "admin")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		rows = LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.ALL_CAMPAIGNS
		).order_by("rank")[:50]
		if not rows.exists():
			rows = LeaderboardService.top_campaigns(limit=50)
			context["use_live"] = True
		context["rows"] = rows
		return context


# ---------------------------------------------------------------------------
# Staff: manage leaderboard settings for a campaign
# ---------------------------------------------------------------------------

@login_required
def leaderboard_settings_view(request, campaign_slug: str):
	if not _is_staff_or_admin(request.user):
		raise PermissionDenied("Staff access required.")

	campaign = get_object_or_404(FundraiserCampaign, slug=campaign_slug)
	lb_settings = LeaderboardService.get_settings(campaign)

	if request.method == "POST":
		lb_settings.public_sellers_visible = "public_sellers_visible" in request.POST
		lb_settings.public_teams_visible = "public_teams_visible" in request.POST
		lb_settings.updated_by = request.user
		lb_settings.save()
		from django.contrib import messages
		messages.success(request, "Leaderboard settings saved.")
		return __import__("django.shortcuts", fromlist=["redirect"]).redirect(
			"leaderboards:settings", campaign_slug=campaign_slug
		)

	return render(request, "leaderboards/settings.html", {
		"campaign": campaign,
		"lb_settings": lb_settings,
	})
