from django.urls import path

from dashboards import views

urlpatterns = [
	path("", views.DashboardHomeView.as_view(), name="home"),
	path("portal/", views.StaffPortalView.as_view(), name="portal"),
	path("owner/", views.OwnerDashboardView.as_view(), name="owner"),
	path("fulfillment/", views.FulfillmentDashboardView.as_view(), name="fulfillment"),
	path("organization/", views.OrganizationDashboardView.as_view(), name="organization"),
	path("team/", views.TeamDashboardView.as_view(), name="team"),
	path("seller/", views.SellerDashboardView.as_view(), name="seller"),
	path("customer/", views.CustomerDashboardView.as_view(), name="customer"),
	path("portal/how-to/", views.StaffHowToView.as_view(), name="how-to"),
	path("portal/operational-settings/", views.OperationalSettingsView.as_view(), name="operational-settings"),
]

app_name = "dashboards"
