from django import forms

from .models import SellerStore


class SellerStoreForm(forms.ModelForm):
	class Meta:
		model = SellerStore
		fields = [
			"display_name",
			"slug",
			"personal_message",
			"seller_goal",
			"profile_photo",
			"team",
			"campaign",
		]
		widgets = {
			"personal_message": forms.Textarea(attrs={"rows": 4}),
		}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		if user is not None:
			# Restrict team choices to teams the seller belongs to
			from teams.models import TeamMembership
			team_ids = TeamMembership.objects.filter(
				member=user, is_active=True
			).values_list("team_id", flat=True)
			self.fields["team"].queryset = self.fields["team"].queryset.filter(
				id__in=team_ids, is_active=True
			)
			# Restrict campaign choices to active campaigns for those teams
			# or campaigns associated with any of the seller's team memberships
			from fundraisers.models import FundraiserCampaign
			campaign_ids = FundraiserCampaign.objects.filter(
				campaign_teams__id__in=team_ids,
				is_active=True,
			).values_list("id", flat=True)
			self.fields["campaign"].queryset = FundraiserCampaign.objects.filter(id__in=campaign_ids)
		self.fields["team"].required = False
		self.fields["campaign"].required = False
