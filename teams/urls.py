from django.urls import path

from .views import (
    PublicTeamDetailView,
    StaffTeamListView,
    TeamCaptainTeamListView,
    join_team_view,
    send_reminder_view,
    staff_move_seller_view,
    team_create_view,
    team_dashboard_view,
    team_delete_view,
    team_edit_view,
    team_members_view,
)

app_name = "teams"

urlpatterns = [
    # Public
    path("<slug:slug>/", PublicTeamDetailView.as_view(), name="public-detail"),
    path("<slug:slug>/join/", join_team_view, name="join"),
    # Authenticated / member
    path("<slug:slug>/dashboard/", team_dashboard_view, name="dashboard"),
    # Captain-only
    path("<slug:slug>/members/", team_members_view, name="members"),
    path("<slug:slug>/remind/", send_reminder_view, name="send-reminder"),
    path("<slug:slug>/edit/", team_edit_view, name="edit"),
    path("<slug:slug>/delete/", team_delete_view, name="delete"),
    path("my-teams/", TeamCaptainTeamListView.as_view(), name="my-teams"),
    path("new/", team_create_view, name="create"),
    # Staff
    path("staff/teams/", StaffTeamListView.as_view(), name="staff-list"),
    path("staff/move-seller/", staff_move_seller_view, name="staff-move-seller"),
]
