from django.urls import path

from .views import (
    StaffAllCampaignsLeaderboardView,
    leaderboard_settings_view,
    public_campaign_leaderboard_view,
    team_leaderboard_view,
)

app_name = "leaderboards"

urlpatterns = [
    # Public campaign leaderboard
    path("campaign/<slug:campaign_slug>/", public_campaign_leaderboard_view, name="campaign"),
    # Team member leaderboard
    path("team/<slug:team_slug>/", team_leaderboard_view, name="team"),
    # Staff: all campaigns
    path("staff/all-campaigns/", StaffAllCampaignsLeaderboardView.as_view(), name="all-campaigns"),
    # Staff: toggle visibility per campaign
    path("staff/campaign/<slug:campaign_slug>/settings/", leaderboard_settings_view, name="settings"),
]
