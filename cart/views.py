from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from products.models import Product, SKU

from .services import CartService


CART_VIEW_URL = "cart:view"


def _is_staff_or_admin(user) -> bool:
	return bool(
		user.is_authenticated
		and (
			user.is_staff
			or user.is_superuser
			or (hasattr(user, "has_any_role") and user.has_any_role("staff", "admin"))
		)
	)


class CartView(TemplateView):
	template_name = "cart/cart.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		CartService.apply_attribution_from_request(self.request)
		cart = CartService.get_or_create_cart(self.request)
		attribution = getattr(cart, "attribution", None)
		has_secure_fundraiser_attribution = bool(
			attribution
			and (
				getattr(attribution, "seller_store_id", None)
				or getattr(attribution, "campaign_id", None)
				or getattr(attribution, "team_ref_id", None)
			)
		)

		context["cart"] = cart
		context["items"] = cart.items.select_related("sku", "sku__product")
		context["saved_items"] = cart.saved_items.select_related("sku", "sku__product")
		context["summary"] = CartService.summary(cart=cart)
		context["has_secure_fundraiser_attribution"] = has_secure_fundraiser_attribution
		estimate_zip = ""
		estimate_state = ""
		if cart.user_id:
			default_addr = cart.user.saved_addresses.filter(is_default=True).first()
			if default_addr:
				estimate_zip = default_addr.postal_code
				estimate_state = default_addr.state
		context["estimate_zip"] = estimate_zip
		context["estimate_state"] = estimate_state
		context["coupon_code"] = cart.coupon_code
		context["coupon_placeholder"] = "POPCORNFUN"
		context["recommended_products"] = (
			Product.objects.public_store()
			.exclude(id__in=cart.items.values_list("sku__product_id", flat=True))[:4]
		)
		return context


@require_POST
def add_to_cart_view(request, sku_id: int):
	sku = get_object_or_404(SKU.objects.select_related("product"), id=sku_id)
	quantity = int(request.POST.get("quantity", "1") or 1)
	try:
		CartService.add_item(request=request, sku=sku, quantity=quantity)
		CartService.apply_attribution_from_request(request)
		messages.success(request, f"Added {sku.product.name} ({sku.size}) to cart.")
	except ValidationError as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)


@require_POST
def update_quantity_view(request, item_id: int):
	quantity = int(request.POST.get("quantity", "1") or 1)
	try:
		CartService.update_item_quantity(request=request, item_id=item_id, quantity=quantity)
		messages.success(request, "Cart quantity updated.")
	except (ValidationError, PermissionDenied) as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)


@require_POST
def remove_item_view(request, item_id: int):
	try:
		CartService.remove_item(request=request, item_id=item_id)
		messages.success(request, "Item removed from cart.")
	except PermissionDenied as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)


@require_POST
def save_for_later_view(request, item_id: int):
	try:
		CartService.save_for_later(request=request, item_id=item_id)
		messages.success(request, "Item saved for later.")
	except PermissionDenied as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)


@require_POST
def move_saved_to_cart_view(request, saved_item_id: int):
	try:
		CartService.move_to_cart(request=request, saved_item_id=saved_item_id)
		messages.success(request, "Saved item moved back to cart.")
	except (ValidationError, PermissionDenied) as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)


@require_POST
def set_attribution_view(request):
	if not _is_staff_or_admin(request.user):
		raise PermissionDenied("Only staff/admin users can manually update cart attribution.")

	CartService.set_attribution(
		request=request,
		fundraiser_campaign=(request.POST.get("campaign") or "").strip(),
		team=(request.POST.get("team") or "").strip(),
		seller=(request.POST.get("seller") or "").strip(),
		overwrite=True,
	)
	messages.success(request, "Cart attribution updated by staff.")
	return redirect(CART_VIEW_URL)


@require_POST
def apply_coupon_view(request):
	cart = CartService.get_or_create_cart(request)
	code = (request.POST.get("coupon_code") or "").strip()
	try:
		from coupons.services import CouponService

		CouponService.apply_coupon_to_cart(
			cart=cart,
			code=code,
			user=request.user if request.user.is_authenticated else None,
		)
		messages.success(request, "Coupon applied.")
	except ValidationError as exc:
		try:
			from coupons.services import CouponService

			CouponService.remove_coupon_from_cart(cart=cart)
		except Exception:
			pass
		messages.error(request, " ".join(exc.messages))
	return redirect(CART_VIEW_URL)


@require_POST
def remove_coupon_view(request):
	cart = CartService.get_or_create_cart(request)
	try:
		from coupons.services import CouponService

		CouponService.remove_coupon_from_cart(cart=cart)
	except Exception:
		pass
	messages.success(request, "Coupon removed.")
	return redirect(CART_VIEW_URL)


def recover_cart_view(request, token: str):
	try:
		CartService.recover_from_token(request=request, token=token)
		messages.success(request, "Your cart was recovered successfully.")
	except (ValidationError, PermissionDenied) as exc:
		messages.error(request, str(exc))
	return redirect(CART_VIEW_URL)
