from django.urls import path

from .views import recover_cart_view, unsubscribe_view

app_name = "abandoned_carts"

urlpatterns = [
    path("cart/<str:token>/", recover_cart_view, name="recover"),
    path("unsubscribe/<str:token>/", unsubscribe_view, name="unsubscribe"),
]
