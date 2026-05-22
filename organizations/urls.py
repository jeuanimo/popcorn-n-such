from django.urls import path

from organizations.views import ConvertOrganizationLeadView, OrganizationCRMDetailView, OrganizationCRMListView

urlpatterns = [
    path("crm/", OrganizationCRMListView.as_view(), name="crm-list"),
    path("crm/<int:organization_id>/", OrganizationCRMDetailView.as_view(), name="crm-detail"),
    path("crm/<int:organization_id>/convert-to-campaign/", ConvertOrganizationLeadView.as_view(), name="convert-to-campaign"),
]
