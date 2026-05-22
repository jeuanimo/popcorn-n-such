"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("", include(("sharing.urls", "sharing"), namespace="sharing")),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("products/", include(("products.urls", "products"), namespace="products")),
    path("coupons/", include(("coupons.urls", "coupons"), namespace="coupons")),
    path("cart/", include(("cart.urls", "cart"), namespace="cart")),
    path("recovery/", include(("abandoned_carts.urls", "abandoned_carts"), namespace="abandoned_carts")),
    path("dashboard/", include("dashboards.urls")),
    path("orders/", include(("orders.urls", "orders"), namespace="orders")),
    path("payments/", include(("payments.urls", "payments"), namespace="payments")),
    path("notifications/", include(("notifications.urls", "notifications"), namespace="notifications")),
    path("teams/", include(("teams.urls", "teams"), namespace="teams")),
    path("store/", include(("sellers.urls", "sellers"), namespace="sellers")),
    path("organizations/", include("organizations.urls")),
    path("fundraisers/", include(("fundraisers.urls", "fundraisers"), namespace="fundraisers")),
    path("shipping/", include(("shipping.urls", "shipping"), namespace="shipping")),
    path("suppliers/", include(("suppliers.urls", "suppliers"), namespace="suppliers")),
    path("purchase-orders/", include(("purchase_orders.urls", "purchase_orders"), namespace="purchase_orders")),
    path("reports/", include(("reports.urls", "reports"), namespace="reports")),
    path("crm/", include(("crm.urls", "crm"), namespace="crm")),
    path("admin/", admin.site.urls),
]

urlpatterns += [
    path("leaderboards/", include(("leaderboards.urls", "leaderboards"), namespace="leaderboards")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
