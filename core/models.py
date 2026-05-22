from django.db import models
from django.conf import settings


class ManagedPageKey(models.TextChoices):
    HOME = "home", "Home"
    ABOUT = "about", "About"
    FUNDRAISING = "fundraising", "Fundraising"
    CORPORATE_GIFTS = "corporate_gifts", "Corporate Gifts"
    CONTACT = "contact", "Contact"
    FAQ = "faq", "FAQ"


class SiteContentBlock(models.Model):
    page_key = models.CharField(max_length=40, choices=ManagedPageKey.choices, db_index=True)
    section_key = models.SlugField(max_length=80, help_text="Use a stable section id, e.g. hero-cta or trust-badges.")
    title = models.CharField(max_length=180, blank=True)
    body = models.TextField(blank=True)
    image = models.ImageField(upload_to="site_content/", blank=True, null=True)
    cta_text = models.CharField(max_length=80, blank=True)
    cta_url = models.CharField(max_length=255, blank=True, help_text="Use a full URL or a site path like /products/.")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_site_content_blocks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_key", "sort_order", "id"]
        unique_together = ("page_key", "section_key")

    def __str__(self) -> str:
        return f"{self.get_page_key_display()} :: {self.section_key}"


class OperationalSettings(models.Model):
    """
    Runtime-editable operational settings for staff/admin portal.
    Environment variables remain defaults; non-empty values here override them.
    """

    pitney_bowes_api_key = models.CharField(max_length=255, blank=True)
    pitney_bowes_api_secret = models.CharField(max_length=255, blank=True)
    pitney_bowes_env = models.CharField(max_length=20, blank=True, default="sandbox")
    pitney_bowes_base_url_sandbox = models.CharField(max_length=255, blank=True)
    pitney_bowes_base_url_prod = models.CharField(max_length=255, blank=True)

    godaddy_api_key = models.CharField(max_length=255, blank=True)
    godaddy_merchant_id = models.CharField(max_length=255, blank=True)
    godaddy_payments_webhook_secret = models.CharField(max_length=255, blank=True)

    contact_email = models.EmailField(blank=True)
    default_from_email = models.EmailField(blank=True)
    email_host = models.CharField(max_length=255, blank=True)
    email_port = models.PositiveIntegerField(default=0)
    email_host_user = models.CharField(max_length=255, blank=True)
    email_host_password = models.CharField(max_length=255, blank=True)
    email_use_tls = models.BooleanField(default=False)

    label_printer_name = models.CharField(max_length=200, blank=True)
    label_printer_ip = models.GenericIPAddressField(null=True, blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_operational_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Operational settings"

    def __str__(self) -> str:
        return "Operational Settings"

# Create your models here.
