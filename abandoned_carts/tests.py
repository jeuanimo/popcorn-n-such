from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cart.models import Cart, CartItem
from orders.models import Order, OrderStatus
from products.models import Product, ProductCategory, SKU

from .models import AbandonedCartEvent, CartRecoveryMessage, EventCloseReason, MessageChannel, RecoveryStage, TokenPurpose
from .services import AbandonedCartRecoveryService

User = get_user_model()
TEST_LOGIN_SECRET = "test-secret-abandoned-carts"


@override_settings(
	EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
	ABANDONED_CART_ABANDONMENT_MINUTES=60,
	ABANDONED_CART_EVENT_EXPIRY_HOURS=168,
	ABANDONED_CART_TOKEN_EXPIRY_HOURS=96,
	SITE_BASE_URL="http://testserver",
)
class AbandonedCartRecoveryTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username="cart-user",
			email="cart-user@example.com",
			password=TEST_LOGIN_SECRET,
			phone_number="+15551234567",
		)
		self.user.profile.marketing_opt_in = True
		self.user.profile.sms_opt_in = True
		self.user.profile.save(update_fields=["marketing_opt_in", "sms_opt_in", "updated_at"])

		self.category = ProductCategory.objects.create(key="popcorn", name="Popcorn")
		self.product = Product.objects.create(
			name="Butter Popcorn",
			slug="butter-popcorn",
			category=self.category,
			flavor="Butter",
			fundraiser_eligible=True,
			standalone_store_eligible=True,
			is_active=True,
		)
		self.sku = SKU.objects.create(
			sku_code="BUTTER-01",
			product=self.product,
			size="Family Tin",
			retail_price=Decimal("19.99"),
			cost_price=Decimal("7.25"),
			inventory_quantity=20,
			is_active=True,
		)
		self.cart = Cart.objects.create(user=self.user, session_key="abc123", is_active=True)
		CartItem.objects.create(cart=self.cart, sku=self.sku, quantity=2)

	def _set_cart_last_activity(self, hours_ago: int):
		cart_time = timezone.now() - timedelta(hours=hours_ago)
		Cart.objects.filter(id=self.cart.id).update(updated_at=cart_time)
		self.cart.refresh_from_db()

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_first_reminder_sent_and_not_duplicated(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=2)

		now = timezone.now()
		first_run = AbandonedCartRecoveryService.process_pending_events(now=now)
		second_run = AbandonedCartRecoveryService.process_pending_events(now=now)

		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertIsNotNone(event.first_reminder_sent_at)
		self.assertEqual(first_run["email_sent"], 1)
		self.assertEqual(first_run["sms_sent"], 1)
		self.assertEqual(second_run["email_sent"], 0)
		self.assertEqual(second_run["sms_sent"], 0)

		self.assertEqual(len(mail.outbox), 1)
		self.assertIn("You left something tasty in your cart", mail.outbox[0].subject)
		self.assertEqual(
			CartRecoveryMessage.objects.filter(event=event, stage=RecoveryStage.FIRST, channel=MessageChannel.EMAIL).count(),
			1,
		)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_sms_only_sent_when_customer_opted_in(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self.user.profile.sms_opt_in = False
		self.user.profile.save(update_fields=["sms_opt_in", "updated_at"])
		self._set_cart_last_activity(hours_ago=2)

		AbandonedCartRecoveryService.process_pending_events(now=timezone.now())

		self.assertEqual(sms_send_mock.call_count, 0)
		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertEqual(
			CartRecoveryMessage.objects.filter(event=event, stage=RecoveryStage.FIRST, channel=MessageChannel.SMS).count(),
			1,
		)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_schedule_progresses_1h_24h_72h(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=80)
		now = timezone.now()

		AbandonedCartRecoveryService.process_pending_events(now=now)
		AbandonedCartRecoveryService.process_pending_events(now=now)
		AbandonedCartRecoveryService.process_pending_events(now=now)

		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertIsNotNone(event.first_reminder_sent_at)
		self.assertIsNotNone(event.second_reminder_sent_at)
		self.assertIsNotNone(event.final_reminder_sent_at)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_processing_stops_when_cart_emptied(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=2)
		AbandonedCartRecoveryService.process_pending_events(now=timezone.now())

		self.cart.items.all().delete()
		AbandonedCartRecoveryService.process_pending_events(now=timezone.now() + timedelta(hours=24))

		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertTrue(event.is_closed)
		self.assertEqual(event.close_reason, EventCloseReason.EMPTIED)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_conversion_tracking_when_completed_order_exists(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=3)
		Order.objects.create(customer=self.user, status=OrderStatus.PLACED)

		result = AbandonedCartRecoveryService.process_pending_events(now=timezone.now())

		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertTrue(event.recovered)
		self.assertIsNotNone(event.recovered_order)
		self.assertTrue(event.is_closed)
		self.assertEqual(event.close_reason, EventCloseReason.RECOVERED)
		self.assertEqual(result["recovered"], 1)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_email_contains_secure_links_without_raw_cart_id(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=2)
		AbandonedCartRecoveryService.process_pending_events(now=timezone.now())

		self.assertEqual(len(mail.outbox), 1)
		message_body = mail.outbox[0].body
		self.assertIn("Recover your cart securely", message_body)
		self.assertIn("Unsubscribe from cart reminders", message_body)
		self.assertNotIn(f"/{self.cart.id}/", message_body)

	@patch("abandoned_carts.services.TwilioSMSProvider.send")
	def test_unsubscribe_link_disables_future_reminders(self, sms_send_mock):
		sms_send_mock.return_value = {"provider": "twilio", "status": "queued"}
		self._set_cart_last_activity(hours_ago=2)
		AbandonedCartRecoveryService.process_pending_events(now=timezone.now())

		unsubscribe_token = (
			AbandonedCartRecoveryService._build_recovery_token(
				event=AbandonedCartEvent.objects.get(cart=self.cart),
				purpose=TokenPurpose.UNSUBSCRIBE,
			)
		)
		response = self.client.get(reverse("abandoned_carts:unsubscribe", args=[unsubscribe_token]))
		self.assertEqual(response.status_code, 200)

		next_run = AbandonedCartRecoveryService.process_pending_events(now=timezone.now() + timedelta(hours=24))
		event = AbandonedCartEvent.objects.get(cart=self.cart)
		self.assertTrue(event.email_unsubscribed)
		self.assertTrue(event.sms_opted_out)
		self.assertEqual(next_run["email_sent"], 0)
		self.assertEqual(next_run["sms_sent"], 0)
