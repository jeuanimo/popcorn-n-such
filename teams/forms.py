from django import forms

from sellers.models import SellerLink

from .models import Team, TeamMembership


class TeamCreateForm(forms.ModelForm):
	class Meta:
		model = Team
		fields = ["campaign", "name", "slug", "team_goal", "team_image"]
		widgets = {
			"slug": forms.TextInput(attrs={"placeholder": "e.g. troop-42-popcorn-2026"}),
		}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		if user is not None and not (user.is_staff or user.is_superuser or user.has_any_role("staff", "admin")):
			# Limit campaigns to those belonging to organizations the user manages or
			# campaigns the user is associated with.  For organization managers we filter
			# by their org; for anyone else we show nothing by default (views guard this).
			from fundraisers.models import FundraiserCampaign

			self.fields["campaign"].queryset = FundraiserCampaign.objects.filter(
				organization__manager=user,
				is_active=True,
			)


class JoinTeamByCodeForm(forms.Form):
	invite_code = forms.CharField(
		max_length=32,
		label="Invite Code",
		widget=forms.TextInput(attrs={"placeholder": "Enter your invite code"}),
	)


class MemberReminderForm(forms.Form):
	subject = forms.CharField(max_length=120, label="Subject")
	message = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), label="Message")
	recipients = forms.ModelMultipleChoiceField(
		queryset=TeamMembership.objects.none(),
		widget=forms.CheckboxSelectMultiple,
		required=False,
		label="Recipients (leave blank to send to all active members)",
	)

	def __init__(self, *args, team=None, **kwargs):
		super().__init__(*args, **kwargs)
		if team is not None:
			self.fields["recipients"].queryset = TeamMembership.objects.filter(
				team=team,
				is_active=True,
			).select_related("member")


class MoveSellerForm(forms.Form):
	seller_link = forms.ModelChoiceField(
		queryset=SellerLink.objects.filter(is_active=True),
		label="Seller",
		empty_label="-- Select seller --",
	)
	from_team = forms.ModelChoiceField(
		queryset=Team.objects.filter(is_active=True),
		label="From team",
		empty_label="-- Select source team --",
	)
	to_team = forms.ModelChoiceField(
		queryset=Team.objects.filter(is_active=True),
		label="To team",
		empty_label="-- Select destination team --",
	)

	def clean(self):
		cleaned_data = super().clean()
		from_team = cleaned_data.get("from_team")
		to_team = cleaned_data.get("to_team")
		if from_team and to_team and from_team == to_team:
			raise forms.ValidationError("Source and destination teams must be different.")
		return cleaned_data
