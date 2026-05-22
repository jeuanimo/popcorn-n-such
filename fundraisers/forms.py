from django import forms

from organizations.models import OrganizationType
from sellers.models import SellerLink
from teams.models import Team

from .models import FundraiserCampaign, FundraiserRequest


class FundraiserCampaignRequestForm(forms.ModelForm):
    class Meta:
        model = FundraiserCampaign
        fields = (
            "organization",
            "campaign_name",
            "slug",
            "description",
            "fundraising_purpose",
            "start_date",
            "end_date",
            "goal_amount",
            "profit_percentage",
            "campaign_image",
            "campaign_banner",
            "public_campaign_link",
            "is_active",
            "teams",
            "sellers",
        )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["teams"].queryset = Team.objects.all()
        self.fields["sellers"].queryset = SellerLink.objects.filter(is_active=True)
        if user is not None:
            self.fields["organization"].queryset = user.managed_organizations.all()


class FundraiserCampaignApprovalForm(forms.ModelForm):
    class Meta:
        model = FundraiserCampaign
        fields = ("status", "is_active", "start_date", "end_date", "profit_percentage", "public_campaign_link")


class FundraiserSignupForm(forms.Form):
    # Contact
    contact_first_name = forms.CharField(max_length=80, label="First name")
    contact_last_name  = forms.CharField(max_length=80, label="Last name")
    contact_email      = forms.EmailField(label="Email address")
    contact_phone      = forms.CharField(max_length=30, required=False, label="Phone (optional)")

    # Organization
    organization_name = forms.CharField(max_length=180, label="Organization / group name")
    org_type = forms.ChoiceField(
        choices=OrganizationType.choices,
        label="Organization type",
        initial="school",
    )
    estimated_sellers = forms.IntegerField(
        min_value=1, max_value=5000, initial=10,
        label="Estimated number of sellers / participants",
    )

    # Campaign intent
    fundraising_purpose = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        label="What are you raising money for?",
    )
    desired_start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        label="Desired start date (optional)",
    )
    goal_amount = forms.DecimalField(
        max_digits=10, decimal_places=2, min_value=100,
        required=False,
        label="Fundraising goal $ (optional)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control form-control-sm")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select form-select-sm")
            else:
                field.widget.attrs.setdefault("class", "form-control form-control-sm")


class FundraiserRequestReviewForm(forms.ModelForm):
    """Staff use only — adds notes and changes status on a FundraiserRequest."""
    class Meta:
        model = FundraiserRequest
        fields = ("status", "staff_notes")
