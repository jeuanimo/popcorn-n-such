from django import forms


class CheckoutForm(forms.Form):
    # Contact info — required for guests, pre-filled for authenticated users
    guest_email = forms.EmailField(
        required=False,
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "your@email.com"}),
    )
    guest_phone = forms.CharField(
        max_length=25,
        required=False,
        label="Phone (optional)",
        widget=forms.TextInput(attrs={"autocomplete": "tel", "placeholder": "+1 555 000 0000"}),
    )

    # Shipping address
    recipient_name = forms.CharField(
        max_length=150,
        label="Full name",
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    shipping_phone = forms.CharField(
        max_length=25,
        required=False,
        label="Shipping phone",
        widget=forms.TextInput(attrs={"autocomplete": "tel"}),
    )
    address_line_1 = forms.CharField(
        max_length=255,
        label="Address",
        widget=forms.TextInput(attrs={"autocomplete": "address-line1"}),
    )
    address_line_2 = forms.CharField(
        max_length=255,
        required=False,
        label="Apt / Suite / Unit",
        widget=forms.TextInput(attrs={"autocomplete": "address-line2"}),
    )
    city = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"autocomplete": "address-level2"}),
    )
    state = forms.CharField(
        max_length=100,
        label="State / Province",
        widget=forms.TextInput(attrs={"autocomplete": "address-level1"}),
    )
    postal_code = forms.CharField(
        max_length=20,
        label="ZIP / Postal code",
        widget=forms.TextInput(attrs={"autocomplete": "postal-code"}),
    )
    country = forms.CharField(max_length=2, initial="US", widget=forms.HiddenInput())

    def clean_country(self):
        value = self.cleaned_data.get("country", "US").upper()
        if len(value) != 2:
            raise forms.ValidationError("Country must be a 2-letter ISO code (e.g. US).")
        return value
