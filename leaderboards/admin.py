from django.contrib import admin

from .models import LeaderboardSettings, LeaderboardSnapshot


@admin.register(LeaderboardSnapshot)
class LeaderboardSnapshotAdmin(admin.ModelAdmin):
	list_display = ("scope", "display_name", "rank", "total_sales_cents", "total_orders", "refreshed_at")
	list_filter = ("scope", "campaign")
	search_fields = ("display_name",)
	readonly_fields = ("refreshed_at",)


@admin.register(LeaderboardSettings)
class LeaderboardSettingsAdmin(admin.ModelAdmin):
	list_display = ("campaign", "public_sellers_visible", "public_teams_visible", "updated_at")
	list_filter = ("public_sellers_visible", "public_teams_visible")
