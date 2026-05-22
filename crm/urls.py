from django.urls import path

from . import views

app_name = "crm"

urlpatterns = [
    path("", views.CRMDashboardView.as_view(), name="dashboard"),
    path("contacts/new/", views.CRMContactCreateView.as_view(), name="contact-create"),
    path("contacts/<int:pk>/", views.CRMContactDetailView.as_view(), name="contact-detail"),
]
