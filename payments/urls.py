from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    path("webhooks/<str:provider>/", views.payment_webhook, name="webhook"),
]

