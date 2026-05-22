from django.urls import path

from .views import CouponAdminListView, CouponCreateView

app_name = "coupons"

urlpatterns = [
    path("admin/", CouponAdminListView.as_view(), name="admin-list"),
    path("admin/create/", CouponCreateView.as_view(), name="admin-create"),
]
