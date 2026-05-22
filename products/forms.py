from django import forms
from django.core.exceptions import ValidationError

from core.validators import validate_upload_file

from .models import Product, SKU


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "slug",
            "description",
            "category",
            "flavor",
            "image",
            "external_image_url",
            "is_active",
            "is_featured",
            "fundraiser_eligible",
            "standalone_store_eligible",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class SKUInventoryForm(forms.ModelForm):
    class Meta:
        model = SKU
        fields = ("inventory_quantity", "low_stock_threshold", "weight_ounces", "is_active")


class ProductSKUCSVUploadForm(forms.Form):
    csv_file = forms.FileField()

    allowed_mime_types = {
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",
    }

    def clean_csv_file(self):
        csv_file = self.cleaned_data["csv_file"]
        validate_upload_file(csv_file, allowed_extensions=(".csv",), max_size_bytes=2_000_000)

        content_type = (getattr(csv_file, "content_type", "") or "").lower()
        if content_type and content_type not in self.allowed_mime_types:
            raise ValidationError("Unsupported CSV MIME type.")

        return csv_file
