from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from payments import views

app_name = "payments"

urlpatterns = [
    # Webhooks are signed server-to-server callbacks and cannot provide CSRF tokens.
    path("webhooks/<str:provider>/", csrf_exempt(views.payment_webhook), name="webhook"),
    path("collect-telemetry/", views.collect_telemetry, name="collect-telemetry"),
]

