from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator

from fundraisers.models import FundraiserRequest

from .models import CustomerProfile, NotificationPreference, ProfileComment, ProfilePost, SavedAddress, UserProfile

User = get_user_model()


class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "phone_number")

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ("display_name",)


class UserProfileBioForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("display_name", "bio")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bio"].widget = forms.Textarea(attrs={"rows": 3, "class": "form-control"})


class AvatarUploadForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("avatar",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["avatar"].required = True


class ProfilePostForm(forms.ModelForm):
    class Meta:
        model = ProfilePost
        fields = ("body", "image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body"].widget = forms.Textarea(attrs={"rows": 3, "placeholder": "What's on your mind?", "class": "form-control"})
        self.fields["image"].required = False


class ProfileCommentForm(forms.ModelForm):
    class Meta:
        model = ProfileComment
        fields = ("body",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body"].widget = forms.TextInput(attrs={"placeholder": "Write a comment…", "class": "form-control form-control-sm"})


class UserAccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone_number")


class ProfileAddressForm(forms.Form):
    recipient_name = forms.CharField(max_length=150, required=False)
    phone_number = forms.CharField(max_length=25, required=False)
    address_line_1 = forms.CharField(max_length=255, required=False)
    address_line_2 = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(
        max_length=20,
        required=False,
        validators=[RegexValidator(r"^[A-Za-z0-9\-\s]{3,20}$", "Enter a valid postal code.")],
    )
    country = forms.CharField(max_length=2, required=False, initial="US")

    REQUIRED_IF_ANY = ("recipient_name", "address_line_1", "city", "state", "postal_code", "country")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def has_address_data(self) -> bool:
        cleaned = getattr(self, "cleaned_data", {})
        return any((cleaned.get(name) or "").strip() for name in self.REQUIRED_IF_ANY)

    def clean(self):
        cleaned = super().clean()
        has_data = any((cleaned.get(name) or "").strip() for name in self.REQUIRED_IF_ANY)
        if has_data:
            for field_name in self.REQUIRED_IF_ANY:
                if not (cleaned.get(field_name) or "").strip():
                    self.add_error(field_name, "This field is required when saving an address.")

        country = (cleaned.get("country") or "").strip().upper()
        if country and len(country) != 2:
            self.add_error("country", "Country must be a 2-letter code.")
        cleaned["country"] = country or "US"
        return cleaned


class NotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = ("email_opt_in", "sms_opt_in")


class SavedAddressForm(forms.ModelForm):
    postal_code = forms.CharField(
        max_length=20,
        validators=[RegexValidator(r"^[A-Za-z0-9\-\s]{3,20}$", "Enter a valid postal code.")],
    )

    class Meta:
        model = SavedAddress
        fields = (
            "label",
            "recipient_name",
            "phone_number",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "postal_code",
            "country",
            "is_default",
        )

    def clean_country(self):
        country = self.cleaned_data["country"].upper().strip()
        if len(country) != 2:
            raise forms.ValidationError("Country must be a 2-letter code.")
        return country

    def clean_state(self):
        state = self.cleaned_data["state"].strip()
        if len(state) < 2:
            raise forms.ValidationError("State or province must be at least 2 characters.")
        return state


class FundraiserJoinForm(forms.Form):
    invite_code = forms.CharField(
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Invite code"}),
    )

    def clean_invite_code(self):
        return self.cleaned_data["invite_code"].strip().upper()


class FundraiserRequestForm(forms.ModelForm):
    class Meta:
        model = FundraiserRequest
        fields = ("organization_name", "goal_description")
