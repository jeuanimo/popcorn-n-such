from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportsDashboardView.as_view(), name="dashboard"),
    path("my/", views.MyReportsDashboardView.as_view(), name="my-dashboard"),
    path("my/fundraiser/<slug:slug>/", views.MyFundraiserReportView.as_view(), name="my-fundraiser"),
    path("my/team/<slug:slug>/", views.MyTeamReportView.as_view(), name="my-team"),

    path("sales/by-date/", views.SalesByDateReportView.as_view(), name="sales-by-date"),
    path("sales/by-product/", views.SalesByProductReportView.as_view(), name="sales-by-product"),
    path("sales/by-sku/", views.SalesBySKUReportView.as_view(), name="sales-by-sku"),
    path("sales/by-fundraiser/", views.SalesByFundraiserReportView.as_view(), name="sales-by-fundraiser"),
    path("sales/by-team/", views.SalesByTeamReportView.as_view(), name="sales-by-team"),
    path("sales/by-seller/", views.SalesBySellerReportView.as_view(), name="sales-by-seller"),
    path("sales/by-organization/", views.SalesByOrganizationReportView.as_view(), name="sales-by-organization"),
    path("sales/by-channel/", views.SalesByChannelReportView.as_view(), name="sales-by-channel"),

    path("tax/", views.TaxReportView.as_view(), name="tax"),
    path("shipping/", views.ShippingReportView.as_view(), name="shipping"),
    path("inventory/", views.InventoryReportView.as_view(), name="inventory"),
    path("supplies/", views.SupplyReportView.as_view(), name="supplies"),
    path("low-stock/", views.LowStockReportView.as_view(), name="low-stock"),
    path("customers/", views.CustomerReportView.as_view(), name="customers"),
    path("supplier-purchases/", views.SupplierPurchaseReportView.as_view(), name="supplier-purchases"),
    path("fundraiser-payouts/", views.FundraiserPayoutEstimateReportView.as_view(), name="fundraiser-payouts"),
]

