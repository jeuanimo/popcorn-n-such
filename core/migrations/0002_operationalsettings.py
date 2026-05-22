from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationalSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pitney_bowes_api_key", models.CharField(blank=True, max_length=255)),
                ("pitney_bowes_api_secret", models.CharField(blank=True, max_length=255)),
                ("pitney_bowes_env", models.CharField(blank=True, default="sandbox", max_length=20)),
                ("pitney_bowes_base_url_sandbox", models.CharField(blank=True, max_length=255)),
                ("pitney_bowes_base_url_prod", models.CharField(blank=True, max_length=255)),
                ("godaddy_api_key", models.CharField(blank=True, max_length=255)),
                ("godaddy_merchant_id", models.CharField(blank=True, max_length=255)),
                ("godaddy_payments_webhook_secret", models.CharField(blank=True, max_length=255)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("default_from_email", models.EmailField(blank=True, max_length=254)),
                ("email_host", models.CharField(blank=True, max_length=255)),
                ("email_port", models.PositiveIntegerField(default=0)),
                ("email_host_user", models.CharField(blank=True, max_length=255)),
                ("email_host_password", models.CharField(blank=True, max_length=255)),
                ("email_use_tls", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_operational_settings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name_plural": "Operational settings"},
        ),
    ]
