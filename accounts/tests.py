from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cart.models import Cart, CartItem
from fundraisers.models import FundraiserInvite, FundraiserParticipation
from orders.models import Order, OrderItem, OrderStatus
from products.models import Product, ProductCategory, SKU

from .models import NotificationPreference, Role, SavedAddress, UserProfile, UserRole

User = get_user_model()


class RoleHelperTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username="multi", password="S3cretPass123!")
		self.customer_role, _ = Role.objects.get_or_create(key=UserRole.CUSTOMER)
		self.seller_role, _ = Role.objects.get_or_create(key=UserRole.SELLER)
		self.user.roles.add(self.customer_role, self.seller_role)

	def test_user_can_have_multiple_roles(self):
		self.assertEqual(self.user.roles.count(), 2)
		self.assertTrue(self.user.is_customer())
		self.assertTrue(self.user.is_seller())
		self.assertFalse(self.user.is_team_captain())


class AccountsAccessTests(TestCase):
	def setUp(self):
		self.customer_role, _ = Role.objects.get_or_create(key=UserRole.CUSTOMER)
		self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)

		self.customer = User.objects.create_user(username="cust", password="S3cretPass123!")
		self.customer.roles.add(self.customer_role)

		self.staff_user = User.objects.create_user(
			username="staffer",
			password="S3cretPass123!",
			is_staff=True,
		)
		self.staff_user.roles.add(self.staff_role)

		self.other_user = User.objects.create_user(username="other", password="S3cretPass123!")
		self.other_user.roles.add(self.customer_role)

	def test_staff_console_requires_staff_or_admin_role(self):
		url = reverse("accounts:staff-console")

		self.client.login(username="cust", password="S3cretPass123!")
		customer_response = self.client.get(url)
		self.assertEqual(customer_response.status_code, 403)

		self.client.logout()
		self.client.login(username="staffer", password="S3cretPass123!")
		staff_response = self.client.get(url)
		self.assertEqual(staff_response.status_code, 200)

	def test_profile_edit_is_authenticated_user_only(self):
		self.client.login(username="cust", password="S3cretPass123!")
		profile_url = reverse("accounts:profile")
		response = self.client.post(
			profile_url,
			{
				"first_name": "Casey",
				"last_name": "Customer",
				"email": "casey@example.com",
				"phone_number": "5551112222",
				"display_name": "Casey C.",
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)

		self.customer.refresh_from_db()
		self.assertEqual(self.customer.first_name, "Casey")
		self.assertEqual(self.customer.profile.display_name, "Casey C.")

		# Other user's profile remains unchanged.
		self.other_user.refresh_from_db()
		self.assertNotEqual(self.other_user.first_name, "Casey")

	def test_address_edit_is_owner_scoped(self):
		owned_address = SavedAddress.objects.create(
			user=self.other_user,
			label="Home",
			recipient_name="Other Person",
			address_line_1="123 Main",
			city="Austin",
			state="TX",
			postal_code="78701",
			country="US",
		)

		self.client.login(username="cust", password="S3cretPass123!")
		url = reverse("accounts:address-edit", kwargs={"public_id": owned_address.public_id})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 404)


class RegistrationFlowTests(TestCase):
	def test_registration_creates_customer_with_profile(self):
		Role.objects.get_or_create(key=UserRole.CUSTOMER)
		response = self.client.post(
			reverse("accounts:register"),
			{
				"username": "newuser",
				"email": "new@popcorn.test",
				"first_name": "New",
				"last_name": "User",
				"phone_number": "5552223333",
				"password1": "S3cretPass123!",
				"password2": "S3cretPass123!",
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)

		user = User.objects.get(username="newuser")
		self.assertTrue(user.is_customer())
		self.assertTrue(UserProfile.objects.filter(user=user).exists())

	def test_registration_honors_next_redirect(self):
		Role.objects.get_or_create(key=UserRole.CUSTOMER)
		response = self.client.post(
			reverse("accounts:register"),
			{
				"username": "nextuser",
				"email": "next@popcorn.test",
				"first_name": "Next",
				"last_name": "User",
				"phone_number": "5557779999",
				"password1": "S3cretPass123!",
				"password2": "S3cretPass123!",
				"next": reverse("accounts:fundraiser-request"),
			},
		)
		self.assertRedirects(response, reverse("accounts:fundraiser-request"))


class CustomerAccountFeatureTests(TestCase):
	def setUp(self):
		self.customer_role, _ = Role.objects.get_or_create(key=UserRole.CUSTOMER)
		self.user = User.objects.create_user(username="buyer", password="S3cretPass123!")
		self.user.roles.add(self.customer_role)
		self.other = User.objects.create_user(username="otherbuyer", password="S3cretPass123!")
		self.other.roles.add(self.customer_role)

		category = ProductCategory.objects.create(key="movie", name="Movie Night")
		product = Product.objects.create(
			name="Cheddar Mix",
			slug="cheddar-mix",
			category=category,
			flavor="Cheddar",
			is_active=True,
		)
		self.sku = SKU.objects.create(
			sku_code="CHED-1",
			product=product,
			size="Bag",
			retail_price="12.00",
			cost_price="4.00",
			inventory_quantity=15,
		)

	def test_customer_cannot_view_other_order_detail(self):
		order = Order.objects.create(customer=self.other, status=OrderStatus.PLACED)
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.get(reverse("orders:order-detail", args=[order.id]))
		self.assertEqual(response.status_code, 404)

	def test_reorder_adds_order_items_to_cart(self):
		order = Order.objects.create(customer=self.user, status=OrderStatus.PLACED)
		OrderItem.objects.create(order=order, sku=self.sku, quantity=2, unit_price_cents=1200)

		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.post(reverse("orders:reorder", args=[order.id]), follow=True)
		self.assertEqual(response.status_code, 200)

		cart = Cart.objects.get(user=self.user, is_active=True)
		cart_item = CartItem.objects.get(cart=cart, sku=self.sku)
		self.assertEqual(cart_item.quantity, 2)

	def test_join_fundraiser_by_invite_code(self):
		invite = FundraiserInvite.objects.create(code="POPCORN2026", campaign_name="Booster")
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.post(reverse("accounts:fundraiser-join"), {"invite_code": invite.code})
		self.assertRedirects(response, reverse("accounts:profile"))
		self.assertTrue(FundraiserParticipation.objects.filter(user=self.user, invite=invite).exists())

	def test_profile_contains_fundraiser_tools(self):
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.get(reverse("accounts:profile"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Fundraiser Tools")
		self.assertContains(response, "Create fundraiser request")

	def test_dashboard_links_to_profile_for_fundraiser_tools(self):
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.get(reverse("accounts:dashboard"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse("accounts:profile") + "#fundraiser-tools")

	def test_authenticated_start_fundraiser_redirects_to_request_form(self):
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.get(reverse("start-fundraiser"))
		self.assertRedirects(response, reverse("accounts:fundraiser-request"))

	def test_signed_out_start_fundraiser_shows_account_gate(self):
		response = self.client.get(reverse("start-fundraiser"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse("accounts:register") + "?next=%2Faccounts%2Ffundraisers%2Frequest%2F")
		self.assertContains(response, reverse("accounts:login") + "?next=%2Faccounts%2Ffundraisers%2Frequest%2F")

	def test_fundraiser_request_page_renders_for_authenticated_user(self):
		self.client.login(username="buyer", password="S3cretPass123!")
		response = self.client.get(reverse("accounts:fundraiser-request"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Create your fundraiser request")

	def test_notification_preferences_update(self):
		self.client.login(username="buyer", password="S3cretPass123!")
		self.client.post(reverse("accounts:preferences"), {"email_opt_in": True, "sms_opt_in": True}, follow=True)
		pref = NotificationPreference.objects.get(user=self.user)
		self.assertTrue(pref.email_opt_in)
		self.assertTrue(pref.sms_opt_in)

	def test_delete_saved_address_is_owner_scoped(self):
		address = SavedAddress.objects.create(
			user=self.user,
			label="Home",
			recipient_name="Buyer",
			address_line_1="123 Main",
			city="Austin",
			state="TX",
			postal_code="78701",
			country="US",
		)

		self.client.login(username="otherbuyer", password="S3cretPass123!")
		response = self.client.post(reverse("accounts:address-delete", kwargs={"public_id": address.public_id}))
		self.assertEqual(response.status_code, 404)
		self.assertTrue(SavedAddress.objects.filter(id=address.id).exists())
