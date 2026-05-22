from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from products.models import Product, ProductCategory, SKU

from .models import Cart, CartItem, SavedForLaterItem
from .services import CartService

User = get_user_model()


class CartFlowTests(TestCase):
	def setUp(self):
		self.category = ProductCategory.objects.create(key="snack", name="Snack")
		self.product = Product.objects.create(
			name="Caramel Popcorn",
			slug="caramel-popcorn",
			category=self.category,
			flavor="Caramel",
			description="Classic caramel crunch.",
			fundraiser_eligible=True,
			standalone_store_eligible=True,
			is_active=True,
		)
		self.sku = SKU.objects.create(
			sku_code="CAR-001",
			product=self.product,
			size="Medium Bag",
			retail_price=Decimal("12.50"),
			cost_price=Decimal("4.50"),
			weight_ounces=Decimal("8.00"),
			inventory_quantity=100,
			is_active=True,
		)

	def test_guest_cart_persists_by_session(self):
		add_url = reverse("cart:add", args=[self.sku.id])
		self.client.post(add_url, {"quantity": 2})
		response = self.client.get(reverse("cart:view"))

		self.assertEqual(response.status_code, 200)
		session_key = self.client.session.session_key
		cart = Cart.objects.get(user__isnull=True, session_key=session_key, is_active=True)
		item = cart.items.get(sku=self.sku)
		self.assertEqual(item.quantity, 2)

	def test_logged_in_user_cannot_remove_other_users_item(self):
		owner = User.objects.create_user(username="owner", password="Password123!")
		User.objects.create_user(username="attacker", password="Password123!")

		owner_cart = Cart.objects.create(user=owner, session_key="owner-session", is_active=True)
		owner_item = CartItem.objects.create(cart=owner_cart, sku=self.sku, quantity=1)

		self.client.login(username="attacker", password="Password123!")
		remove_url = reverse("cart:remove-item", args=[owner_item.id])
		self.client.post(remove_url)

		self.assertTrue(CartItem.objects.filter(id=owner_item.id).exists())

	def test_guest_cart_merges_into_user_cart_on_login(self):
		add_url = reverse("cart:add", args=[self.sku.id])
		self.client.post(add_url, {"quantity": 2})

		user = User.objects.create_user(username="merge-user", password="Password123!")
		user_cart = Cart.objects.create(user=user, session_key="user-session", is_active=True)
		CartItem.objects.create(cart=user_cart, sku=self.sku, quantity=1)

		self.client.login(username="merge-user", password="Password123!")
		response = self.client.get(reverse("cart:view"))
		self.assertEqual(response.status_code, 200)

		merged_cart = Cart.objects.get(user=user, is_active=True)
		merged_item = merged_cart.items.get(sku=self.sku)
		self.assertEqual(merged_item.quantity, 3)
		self.assertEqual(Cart.objects.filter(user__isnull=True, is_active=True).count(), 0)

	def test_save_for_later_and_move_back(self):
		add_url = reverse("cart:add", args=[self.sku.id])
		self.client.post(add_url, {"quantity": 2})

		cart = Cart.objects.get(user__isnull=True, session_key=self.client.session.session_key, is_active=True)
		item = cart.items.get(sku=self.sku)

		self.client.post(reverse("cart:save-for-later", args=[item.id]))
		self.assertFalse(CartItem.objects.filter(cart=cart, sku=self.sku).exists())
		self.assertTrue(SavedForLaterItem.objects.filter(cart=cart, sku=self.sku).exists())

		saved = SavedForLaterItem.objects.get(cart=cart, sku=self.sku)
		self.client.post(reverse("cart:move-to-cart", args=[saved.id]))
		self.assertTrue(CartItem.objects.filter(cart=cart, sku=self.sku, quantity=2).exists())
		self.assertFalse(SavedForLaterItem.objects.filter(cart=cart, sku=self.sku).exists())

	def test_recovery_token_success_and_failure_and_expiry(self):
		self.client.post(reverse("cart:add", args=[self.sku.id]), {"quantity": 1})
		cart = Cart.objects.get(user__isnull=True, session_key=self.client.session.session_key, is_active=True)
		token = CartService.generate_recovery_token(cart=cart)

		self.client.cookies.clear()
		response = self.client.get(reverse("cart:recover", args=[token]))
		self.assertEqual(response.status_code, 302)
		recovered = Cart.objects.get(id=cart.id)
		self.assertEqual(recovered.session_key, self.client.session.session_key)

		invalid_response = self.client.get(reverse("cart:recover", args=["bad-token"]))
		self.assertEqual(invalid_response.status_code, 302)

		with self.assertRaisesMessage(ValidationError, "Invalid or expired recovery link."):
			CartService.recover_from_token(request=response.wsgi_request, token=token, max_age=-1)

	def test_summary_uses_server_side_sku_prices(self):
		self.client.post(reverse("cart:add", args=[self.sku.id]), {"quantity": 2})
		cart = Cart.objects.get(user__isnull=True, session_key=self.client.session.session_key, is_active=True)

		summary = CartService.summary(cart=cart)
		self.assertEqual(summary["subtotal"], Decimal("25.00"))
		self.assertEqual(summary["total"], Decimal("25.00"))
