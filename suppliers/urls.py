from django.urls import path

from suppliers import views

app_name = "suppliers"

urlpatterns = [
    path("", views.SupplierListView.as_view(), name="list"),
    path("new/", views.SupplierCreateView.as_view(), name="create"),
    path("import-csv/", views.SupplierCSVImportView.as_view(), name="import-csv"),
    path("<int:supplier_id>/", views.SupplierDetailView.as_view(), name="detail"),
    path("<int:supplier_id>/edit/", views.SupplierUpdateView.as_view(), name="edit"),
    path("<int:supplier_id>/delete/", views.SupplierDeleteView.as_view(), name="delete"),
]
