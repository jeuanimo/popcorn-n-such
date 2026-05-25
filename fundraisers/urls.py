from django.urls import path

from .views import (
    FundraiserCampaignDashboardView,
    OrganizationManagerCampaignListView,
    PublicFundraiserCampaignDetailView,
    PublicFundraiserCampaignListView,
    StaffCampaignQueueView,
    StaffFundraiserRequestQueueView,
    campaign_create_view,
    campaign_seller_join_view,
    fundraiser_request_delete_view,
    fundraiser_campaign_delete_view,
    fundraiser_signup_thanks_view,
    fundraiser_signup_view,
    staff_approve_campaign_view,
    staff_toggle_campaign_live_view,
    staff_provision_campaign_view,
)

app_name = "fundraisers"

urlpatterns = [
    # Public
    path("", PublicFundraiserCampaignListView.as_view(), name="public-campaign-list"),
    path("start/", fundraiser_signup_view, name="signup"),
    path("start/thanks/", fundraiser_signup_thanks_view, name="signup-thanks"),
    path("campaign/<slug:slug>/", PublicFundraiserCampaignDetailView.as_view(), name="public-campaign-detail"),
    path("campaign/<slug:slug>/join-as-seller/", campaign_seller_join_view, name="seller-join"),
    # Organization manager
    path("manage/", OrganizationManagerCampaignListView.as_view(), name="manager-campaigns"),
    path("manage/new/", campaign_create_view, name="manager-campaign-create"),
    path("manage/<slug:slug>/dashboard/", FundraiserCampaignDashboardView.as_view(), name="campaign-dashboard"),
    # Staff
    path("staff/queue/", StaffCampaignQueueView.as_view(), name="staff-campaign-queue"),
    path("staff/<slug:slug>/approve/", staff_approve_campaign_view, name="staff-campaign-approve"),
    path("staff/<slug:slug>/live-toggle/", staff_toggle_campaign_live_view, name="staff-campaign-live-toggle"),
    path("staff/requests/", StaffFundraiserRequestQueueView.as_view(), name="staff-request-queue"),
    path("staff/requests/<int:pk>/", staff_provision_campaign_view, name="staff-provision-campaign"),
    path("staff/requests/<int:pk>/delete/", fundraiser_request_delete_view, name="staff-request-delete"),
    path("staff/<slug:slug>/delete/", fundraiser_campaign_delete_view, name="staff-campaign-delete"),
]
