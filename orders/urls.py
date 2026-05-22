from django.urls import path

from .views import (
    CheckoutCompleteView,
    CheckoutPaymentReturnView,
    CheckoutReviewView,
    CheckoutView,
    CustomerOrderDetailView,
    CustomerOrderListView,
    StaffOrderListView,
    SubscriptionsView,
    cancel_subscription_view,
    create_subscription_view,
    pause_subscription_view,
    reorder_view,
    resume_subscription_view,
)

app_name = "orders"

urlpatterns = [
    path("staff/", StaffOrderListView.as_view(), name="staff-list"),
    path("my-orders/", CustomerOrderListView.as_view(), name="my-orders"),
    path("my-orders/<int:pk>/", CustomerOrderDetailView.as_view(), name="order-detail"),
    path("my-orders/<int:order_id>/reorder/", reorder_view, name="reorder"),
    path("my-orders/<int:order_id>/subscribe/", create_subscription_view, name="subscribe"),
    path("subscriptions/", SubscriptionsView.as_view(), name="subscriptions"),
    path("subscriptions/<int:subscription_id>/pause/", pause_subscription_view, name="subscription-pause"),
    path("subscriptions/<int:subscription_id>/resume/", resume_subscription_view, name="subscription-resume"),
    path("subscriptions/<int:subscription_id>/cancel/", cancel_subscription_view, name="subscription-cancel"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("checkout/review/", CheckoutReviewView.as_view(), name="checkout-review"),
    path("checkout/payment-return/", CheckoutPaymentReturnView.as_view(), name="checkout-payment-return"),
    path("checkout/complete/<str:order_number>/", CheckoutCompleteView.as_view(), name="checkout-complete"),
]
