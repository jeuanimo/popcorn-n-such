from django import forms

from .models import Coupon


class CouponAdminForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code",
            "description",
            "discount_type",
            "percent_off",
            "amount_off_cents",
            "currency",
            "start_date",
            "end_date",
            "is_active",
            "usage_limit",
            "per_customer_limit",
            "minimum_cart_subtotal_cents",
            "applies_to_fundraiser_orders",
            "applies_to_products",
            "applies_to_categories",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "applies_to_products": forms.SelectMultiple(attrs={"size": 8}),
            "applies_to_categories": forms.SelectMultiple(attrs={"size": 6}),
        }

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip().upper()
