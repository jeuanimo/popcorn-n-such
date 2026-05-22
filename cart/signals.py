from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import Cart
from .services import CartService


@receiver(user_logged_in)
def merge_guest_cart_on_login(sender, request, user, **kwargs):
    # Signals can fire before request.user reflects the authenticated account.
    session_key = CartService._ensure_session_key(request)
    user_cart, _ = Cart.objects.get_or_create(user=user, is_active=True, defaults={"session_key": session_key})

    session_cart_id = request.session.get(CartService.SESSION_CART_ID_KEY)
    guest_cart = None
    if session_cart_id:
        guest_cart = Cart.objects.filter(id=session_cart_id, user__isnull=True, is_active=True).first()
    if not guest_cart:
        guest_cart = Cart.objects.filter(user__isnull=True, session_key=session_key, is_active=True).first()

    if guest_cart and guest_cart.id != user_cart.id:
        CartService.merge_carts(user_cart=user_cart, guest_cart=guest_cart)

    request.session[CartService.SESSION_CART_ID_KEY] = user_cart.id
