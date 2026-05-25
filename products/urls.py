from django.urls import path

from .views import (
    AdminProductListView,
    ProductCreateView,
    ProductDeleteView,
    ProductSKUCSVImportView,
    ProductCategoryView,
    ProductDetailView,
    ProductListView,
    ProductUpdateView,
    SKUBulkDeleteView,
    SKUCreateView,
    SKUCSVExportView,
    SKUCSVTemplateView,
    SKUDeleteView,
    SKUManagementView,
    SKUUpdateView,
)

app_name = "products"

urlpatterns = [
    path("admin/products/", AdminProductListView.as_view(), name="admin-list"),
    path("admin/products/add/", ProductCreateView.as_view(), name="admin-create"),
    path("admin/products/<int:pk>/edit/", ProductUpdateView.as_view(), name="admin-edit"),
    path("admin/products/<int:pk>/delete/", ProductDeleteView.as_view(), name="admin-delete"),
    path("admin/skus/", SKUManagementView.as_view(), name="sku-management"),
    path("admin/skus/add/", SKUCreateView.as_view(), name="sku-create"),
    path("admin/skus/export.csv", SKUCSVExportView.as_view(), name="sku-export"),
    path("admin/skus/import/template.csv", SKUCSVTemplateView.as_view(), name="csv-template"),
    path("admin/skus/import/", ProductSKUCSVImportView.as_view(), name="csv-import"),
    path("admin/skus/<int:pk>/edit/", SKUUpdateView.as_view(), name="sku-edit"),
    path("admin/skus/bulk-delete/", SKUBulkDeleteView.as_view(), name="sku-bulk-delete"),
    path("admin/skus/<int:pk>/delete/", SKUDeleteView.as_view(), name="sku-delete"),
	path("admin/skus/<str:sku_code>/", SKUManagementView.as_view(), name="sku-update"),
    path("category/<slug:category_key>/", ProductCategoryView.as_view(), name="category"),
    path("", ProductListView.as_view(), name="list"),
    path("<slug:slug>/", ProductDetailView.as_view(), name="detail"),
]
