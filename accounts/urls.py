from django.urls import include, path

from .views import (
    AccountDashboardView,
    RegisterView,
    create_fundraiser_request_view,
    delete_saved_address_view,
    edit_saved_address_view,
    join_fundraiser_view,
    notification_preferences_view,
    profile_view,
    saved_addresses_view,
    staff_console_view,
)
from .admin_user_create_view import admin_user_create_view

app_name = "accounts"

urlpatterns = [
    path("", include("django.contrib.auth.urls")),
    path("register/", RegisterView.as_view(), name="register"),
    path("dashboard/", AccountDashboardView.as_view(), name="dashboard"),
    path("profile/", profile_view, name="profile"),
    path("preferences/", notification_preferences_view, name="preferences"),
    path("addresses/", saved_addresses_view, name="addresses"),
    path("addresses/<uuid:public_id>/edit/", edit_saved_address_view, name="address-edit"),
    path("addresses/<uuid:public_id>/delete/", delete_saved_address_view, name="address-delete"),
    path("fundraisers/join/", join_fundraiser_view, name="fundraiser-join"),
    path("fundraisers/request/", create_fundraiser_request_view, name="fundraiser-request"),
    path("staff/", staff_console_view, name="staff-console"),
    path("staff/create-user/", admin_user_create_view, name="admin-user-create"),
]
