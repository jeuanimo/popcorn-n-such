from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from notifications.models import NotificationDeliveryChannel, NotificationDeliveryLog, NotificationEvent, StaffAlertEventType
from orders.models import Order, OrderStatus, PaymentStatus
from payments.models import PaymentStatus as TxStatus, PaymentTransaction, PaymentProvider
from payments.services import handle_payment_failure, handle_payment_success
from products.models import Product, ProductCategory, SKU

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PaymentConfirmationAlertTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff", password="pw", email="staff@example.com", is_staff=True)
        cat = ProductCategory.objects.create(key="pop", name="Popcorn")
        product = Product.objects.create(name="P", slug="p", category=cat, flavor="plain", is_active=True)
        sku = SKU.objects.create(
            sku_code="SKU",
            product=product,
            size="s",
            retail_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            inventory_quantity=10,
            is_active=True,
        )
        self.order = Order.objects.create(
            customer=self.staff,  # doesn't matter for staff alert
            subtotal_cents=1000,
            tax_cents=0,
            shipping_cents=0,
            discount_cents=0,
            total_cents=1000,
            status=OrderStatus.PAID,
            payment_status=PaymentStatus.CAPTURED,
        )
        # Add one item for email render path
        from orders.models import OrderItem

        OrderItem.objects.create(
            order=self.order,
            product=product,
            sku=sku,
            product_name_snapshot=product.name,
            sku_snapshot={"sku_code": sku.sku_code, "size": sku.size, "retail_price": str(sku.retail_price)},
            quantity=1,
            unit_price_cents=1000,
            line_total_cents=1000,
            weight_ounces=sku.weight_ounces,
            fundraiser_eligible=True,
        )

    @patch("notifications.alerts.send_mail")
    def test_payment_confirmed_triggers_staff_internal_alert(self, _send_mail):
        tx = PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY,
            status=TxStatus.CREATED,
            order=self.order,
            amount_cents=1000,
            currency="USD",
        )
        handle_payment_success(payment_transaction=tx)

        event = NotificationEvent.objects.filter(event_type=StaffAlertEventType.NEW_PAID_ORDER).first()
        self.assertIsNotNone(event)
        delivery = NotificationDeliveryLog.objects.filter(
            event=event,
            user=self.staff,
            channel=NotificationDeliveryChannel.INTERNAL,
        ).first()
        self.assertIsNotNone(delivery)

    @patch("notifications.alerts.send_mail")
    def test_payment_failed_triggers_staff_internal_alert(self, _send_mail):
        tx = PaymentTransaction.objects.create(
            provider=PaymentProvider.GODADDY,
            status=TxStatus.CREATED,
            order=self.order,
            amount_cents=1000,
            currency="USD",
        )
        handle_payment_failure(payment_transaction=tx, failure_code="declined", failure_message="Declined")

        event = NotificationEvent.objects.filter(event_type=StaffAlertEventType.FAILED_PAYMENT).first()
        self.assertIsNotNone(event)
        delivery = NotificationDeliveryLog.objects.filter(
            event=event,
            user=self.staff,
            channel=NotificationDeliveryChannel.INTERNAL,
        ).first()
        self.assertIsNotNone(delivery)
