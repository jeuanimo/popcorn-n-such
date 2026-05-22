from django.urls import path

from purchase_orders import views

app_name = "purchase_orders"

urlpatterns = [
	path("reorder-suggestions/", views.LowSupplyReorderSuggestionsView.as_view(), name="reorder-suggestions"),
]

