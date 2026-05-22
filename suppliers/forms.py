from django import forms

from .models import Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "name",
            "category",
            "status",
            "contact_person",
            "email",
            "phone",
            "website",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "postal_code",
            "country",
            "products_supplies_provided",
            "payment_terms",
            "average_lead_time_days",
            "vendor_tax_id",
            "rating",
            "notes",
            "last_contact_date",
            "next_follow_up_date",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "contact_person": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "website": forms.URLInput(attrs={"class": "form-control"}),
            "address_line_1": forms.TextInput(attrs={"class": "form-control"}),
            "address_line_2": forms.TextInput(attrs={"class": "form-control"}),
            "city": forms.TextInput(attrs={"class": "form-control"}),
            "state": forms.TextInput(attrs={"class": "form-control"}),
            "postal_code": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "products_supplies_provided": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "payment_terms": forms.TextInput(attrs={"class": "form-control"}),
            "average_lead_time_days": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "vendor_tax_id": forms.TextInput(attrs={"class": "form-control"}),
            "rating": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 5}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "last_contact_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "next_follow_up_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }


class SupplierCSVImportForm(forms.Form):
    csv_file = forms.FileField(widget=forms.FileInput(attrs={"class": "form-control"}))
