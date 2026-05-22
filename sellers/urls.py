from django.urls import path

from .views import (
    PublicSellerStoreView,
    StaffSellerStoreListView,
    my_stores_view,
    seller_dashboard_view,
    seller_store_edit_view,
)

app_name = "sellers"

urlpatterns = [
    # Public storefront — no login required
    path("<slug:slug>/", PublicSellerStoreView.as_view(), name="public-store"),
    # Seller dashboard (personal metrics)
    path("<slug:slug>/dashboard/", seller_dashboard_view, name="dashboard"),
    # Create / edit own store
    path("new/", seller_store_edit_view, name="create"),
    path("<slug:slug>/edit/", seller_store_edit_view, name="edit"),
    # My stores list
    path("my-stores/", my_stores_view, name="my-stores"),
    # Staff management
    path("staff/stores/", StaffSellerStoreListView.as_view(), name="staff-list"),
]
