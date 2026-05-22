from django.urls import path

from .views import (
    CartView,
    add_to_cart_view,
    apply_coupon_view,
    move_saved_to_cart_view,
    recover_cart_view,
    remove_item_view,
    remove_coupon_view,
    save_for_later_view,
    set_attribution_view,
    update_quantity_view,
)

app_name = "cart"

urlpatterns = [
    path("", CartView.as_view(), name="view"),
    path("add/<int:sku_id>/", add_to_cart_view, name="add"),
    path("item/<int:item_id>/update/", update_quantity_view, name="update-quantity"),
    path("item/<int:item_id>/remove/", remove_item_view, name="remove-item"),
    path("item/<int:item_id>/save/", save_for_later_view, name="save-for-later"),
    path("saved/<int:saved_item_id>/move/", move_saved_to_cart_view, name="move-to-cart"),
    path("coupon/apply/", apply_coupon_view, name="apply-coupon"),
    path("coupon/remove/", remove_coupon_view, name="remove-coupon"),
    path("attribution/update/", set_attribution_view, name="set-attribution"),
    path("recover/<str:token>/", recover_cart_view, name="recover"),
]
