from django.contrib import admin

from .models import (
	FundraiserCampaign,
	FundraiserInvite,
	FundraiserParticipation,
	FundraiserRequest,
)


@admin.register(FundraiserCampaign)
class FundraiserCampaignAdmin(admin.ModelAdmin):
	list_display = ("campaign_name", "organization", "status", "is_active", "start_date", "end_date")
	list_filter = ("status", "is_active", "start_date", "end_date")
	search_fields = ("campaign_name", "slug", "organization__name")
	filter_horizontal = ("teams", "sellers")


@admin.register(FundraiserInvite)
class FundraiserInviteAdmin(admin.ModelAdmin):
	list_display = ("code", "campaign_name", "is_active", "expires_at")
	search_fields = ("code", "campaign_name", "team_name", "seller_name")


@admin.register(FundraiserParticipation)
class FundraiserParticipationAdmin(admin.ModelAdmin):
	list_display = ("user", "invite", "joined_at")
	search_fields = ("user__username", "invite__campaign_name", "invite__code")


@admin.register(FundraiserRequest)
class FundraiserRequestAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "organization_name", "status", "created_at")
	list_filter = ("status",)
	search_fields = ("user__username", "organization_name")
