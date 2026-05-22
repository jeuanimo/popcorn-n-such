from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_staff_alerts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0006_order_coupon_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notification_type", models.CharField(choices=[
                    ("new_order", "New order"),
                    ("order_shipped", "Order shipped"),
                    ("delivery_update", "Delivery update"),
                    ("abandoned_cart_reminder", "Abandoned cart reminder"),
                    ("fundraiser_invite", "Fundraiser invite"),
                    ("team_invite", "Team invite"),
                    ("seller_joined_team", "Seller joined team"),
                    ("team_milestone", "Team milestone"),
                    ("low_inventory", "Low inventory"),
                    ("low_supplies", "Low supplies"),
                    ("csv_import_complete", "CSV import complete"),
                    ("payment_failed", "Payment failed"),
                    ("label_created", "Label created"),
                ], max_length=64)),
                ("title", models.CharField(max_length=200)),
                ("message", models.TextField(blank=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("read_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="user_notifications", to="orders.order")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                ("receive_in_app", models.BooleanField(default=True)),
                ("receive_email", models.BooleanField(default=True)),
                ("receive_sms", models.BooleanField(default=False)),
                ("sms_opt_in", models.BooleanField(default=False)),
                ("enabled_types", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="notification_center_preference", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["user__username"],
            },
        ),
        migrations.AddField(
            model_name="notificationdeliverylog",
            name="notification",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="notifications.notification"),
        ),
        migrations.AlterField(
            model_name="notificationdeliverylog",
            name="event",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="notifications.notificationevent"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "read_at", "created_at"], name="notificatio_user_id_2d9882_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "notification_type", "created_at"], name="notificatio_user_id_f18561_idx"),
        ),
    ]

