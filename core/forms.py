from django import forms
from .models import SiteContentBlock

class ContactForm(forms.Form):
    name = forms.CharField(label="Your Name", max_length=100, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Name"}))
    email = forms.EmailField(label="Your Email", widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}))
    message = forms.CharField(label="Message", widget=forms.Textarea(attrs={"class": "form-control", "placeholder": "How can we help you?", "rows": 5}))


class SiteContentBlockForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["page_key"].label = "Which Page Are You Editing?"
        self.fields["section_key"].label = "Section Name (Internal)"
        self.fields["title"].label = "Heading Text"
        self.fields["body"].label = "Main Text / Paragraphs"
        self.fields["image"].label = "Image for This Section"
        self.fields["cta_text"].label = "Button Text"
        self.fields["cta_url"].label = "Button Link"
        self.fields["sort_order"].label = "Display Order"
        self.fields["is_active"].label = "Show this section on the site"

        self.fields["page_key"].help_text = "Pick the page where this content should appear."
        self.fields["section_key"].help_text = "Used by the system to place content in the right area. Keep this short and consistent, like hero, testimonial, or promo-banner."
        self.fields["title"].help_text = "Large headline text users will see."
        self.fields["body"].help_text = "Supporting text shown under the heading."
        self.fields["image"].help_text = "Optional. Upload an image for this section."
        self.fields["cta_text"].help_text = "Optional button label, for example: Shop Now, Learn More, Start Fundraiser."
        self.fields["cta_url"].help_text = "Optional button destination, for example: /products/ or https://example.com/page."
        self.fields["sort_order"].help_text = "Lower numbers show first (0 appears before 1, 2, 3...)."
        self.fields["is_active"].help_text = "Turn off to hide this section without deleting it."

    class Meta:
        model = SiteContentBlock
        fields = [
            "page_key",
            "section_key",
            "title",
            "body",
            "image",
            "cta_text",
            "cta_url",
            "sort_order",
            "is_active",
        ]
        widgets = {
            "page_key": forms.Select(attrs={"class": "form-select"}),
            "section_key": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "cta_text": forms.TextInput(attrs={"class": "form-control"}),
            "cta_url": forms.TextInput(attrs={"class": "form-control"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class OperationalSettingsForm(forms.Form):
    # ── Shipping ────────────────────────────────────────────────
    shipping_provider = forms.ChoiceField(
        required=False,
        choices=[
            ("usps", "USPS (live rates)"),
            ("pitney_bowes", "Pitney Bowes (live rates)"),
            ("flat_rate", "Flat Rate (no API)"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    shipping_markup_percent = forms.DecimalField(
        required=False, min_value=0, max_value=100,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}),
    )
    shipping_from_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Popcorn N Such"}))
    shipping_from_address_line_1 = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Street address"}))
    shipping_from_address_line_2 = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Suite, unit, etc. (optional)"}))
    shipping_from_city = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "City"}))
    shipping_from_state = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "maxlength": "2", "placeholder": "IL"}))
    shipping_from_postal_code = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "ZIP code"}))
    shipping_from_country = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "maxlength": "2", "placeholder": "US"}))
    shipping_default_weight_oz = forms.DecimalField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.5"}))
    estimated_shipping_cents = forms.IntegerField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": "form-control"}))

    usps_client_id = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    usps_client_secret = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))
    usps_env = forms.ChoiceField(required=False, choices=[("sandbox", "Sandbox"), ("production", "Production")], widget=forms.Select(attrs={"class": "form-select"}))
    usps_base_url_sandbox = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "https://api-sandbox.usps.com"}))
    usps_base_url_prod = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "https://api.usps.com"}))
    pitney_bowes_api_key = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    pitney_bowes_api_secret = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))
    pitney_bowes_env = forms.ChoiceField(required=False, choices=[("sandbox", "sandbox"), ("production", "production")], widget=forms.Select(attrs={"class": "form-select"}))
    pitney_bowes_base_url_sandbox = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    pitney_bowes_base_url_prod = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_api_key = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_api_secret = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))
    godaddy_merchant_id = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_webhook_secret = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))
    godaddy_payments_base_url = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_create_session_path = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_verify_path = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_refund_path = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_test_path = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    godaddy_payments_test_method = forms.ChoiceField(
        required=False,
        choices=[("GET", "GET"), ("POST", "POST")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    godaddy_payments_allowed_redirect_hosts = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    contact_email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    default_from_email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    email_host = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email_port = forms.IntegerField(required=False, min_value=0, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    email_host_user = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email_host_password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={"class": "form-control"}))
    email_use_tls = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    label_printer_name = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. ZDesigner GK420d"}))
    label_printer_ip = forms.GenericIPAddressField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 192.168.1.100"}))
