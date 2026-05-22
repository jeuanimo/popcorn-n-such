from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0005_checkout_system"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("godaddy", "GoDaddy Payments"), ("stripe", "Stripe"), ("paypal", "PayPal")], max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("pending", "Pending"),
                            ("authorized", "Authorized"),
                            ("captured", "Captured"),
                            ("confirmed", "Confirmed"),
                            ("failed", "Failed"),
                            ("refunded", "Refunded"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="created",
                        max_length=20,
                    ),
                ),
                ("amount_cents", models.PositiveIntegerField()),
                ("currency", models.CharField(default="USD", max_length=10)),
                ("provider_transaction_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("provider_session_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("checkout_url", models.URLField(blank=True)),
                ("idempotency_key", models.CharField(blank=True, db_index=True, max_length=128)),
                ("provider_metadata", models.JSONField(blank=True, default=dict)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("failure_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment_transactions",
                        to="orders.order",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["provider", "status"], name="payments_pay_provider_d5a4f9_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PaymentEventLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("godaddy", "GoDaddy Payments"), ("stripe", "Stripe"), ("paypal", "PayPal")], max_length=32)),
                ("event_type", models.CharField(max_length=100)),
                ("external_event_id", models.CharField(blank=True, db_index=True, max_length=128)),
                ("signature_valid", models.BooleanField(default=False)),
                ("request_id", models.CharField(blank=True, max_length=128)),
                ("headers", models.JSONField(blank=True, default=dict)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("processing_error", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                (
                    "transaction",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="event_logs",
                        to="payments.paymenttransaction",
                    ),
                ),
            ],
            options={
                "ordering": ["-received_at"],
                "indexes": [
                    models.Index(fields=["provider", "event_type"], name="payments_pay_provider_5e3c46_idx"),
                ],
            },
        ),
    ]

