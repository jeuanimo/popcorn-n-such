from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from payments import views
from payments.views_authorize import poynt_authorize_callback

app_name = "payments"

urlpatterns = [
    # One-time merchant onboarding callback, not part of checkout. Disabled by
    # default — see docs/PAYMENTS.md.
    path("poynt/callback/", poynt_authorize_callback, name="poynt_authorize_callback"),
    # Webhooks are signed server-to-server callbacks and cannot provide CSRF tokens.
    path("webhooks/<str:provider>/", csrf_exempt(views.payment_webhook), name="webhook"),
    path("collect-telemetry/", views.collect_telemetry, name="collect-telemetry"),
]
