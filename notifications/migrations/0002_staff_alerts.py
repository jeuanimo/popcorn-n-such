from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
        ("orders", "0005_checkout_system"),
        ("products", "0004_product_external_image_url_csvimportbatch_and_more"),
        ("teams", "0003_alter_team_options_team_campaign_team_invite_code_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffAlertPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                ("receive_email", models.BooleanField(default=True)),
                ("receive_sms", models.BooleanField(default=False)),
                ("receive_internal", models.BooleanField(default=True)),
                ("sms_opt_in", models.BooleanField(default=False)),
                ("enabled_events", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="staff_alert_preference",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["user__username"]},
        ),
        migrations.CreateModel(
            name="NotificationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("new_paid_order", "New paid order"),
                            ("new_fundraiser_signup", "New fundraiser signup"),
                            ("new_team_created", "New team created"),
                            ("low_product_inventory", "Low product inventory"),
                            ("low_supply_inventory", "Low supply inventory"),
                            ("failed_payment", "Failed payment"),
                            ("shipping_label_created", "Shipping label created"),
                            ("address_validation_failed", "Address validation failed"),
                            ("large_order_received", "Large order received"),
                            ("csv_import_completed", "CSV import completed"),
                            ("csv_import_failed", "CSV import failed"),
                        ],
                        max_length=64,
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("message", models.TextField(blank=True)),
                ("severity", models.CharField(default="info", max_length=20)),
                ("dedupe_key", models.CharField(blank=True, db_index=True, max_length=120)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staff_events",
                        to="orders.order",
                    ),
                ),
                (
                    "sku",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staff_events",
                        to="products.sku",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="staff_events",
                        to="teams.team",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["event_type", "created_at"], name="notifications_event_type_created_idx")],
            },
        ),
        migrations.CreateModel(
            name="NotificationDeliveryLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel", models.CharField(choices=[("email", "Email"), ("sms", "SMS"), ("internal", "Internal")], max_length=12)),
                ("status", models.CharField(choices=[("sent", "Sent"), ("failed", "Failed"), ("skipped", "Skipped")], default="sent", max_length=10)),
                ("recipient", models.CharField(blank=True, max_length=255)),
                ("subject", models.CharField(blank=True, max_length=255)),
                ("body", models.TextField(blank=True)),
                ("failure_reason", models.CharField(blank=True, max_length=255)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="notifications.notificationevent"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_deliveries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["user", "channel", "status"], name="notifications_delivery_user_channel_status_idx"),
                    models.Index(fields=["user", "read_at"], name="notifications_delivery_user_read_idx"),
                ],
            },
        ),
    ]

