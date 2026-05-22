from django.contrib import admin

from .models import Team, TeamMembership, TeamReminderLog


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    extra = 0
    fields = ("member", "role", "is_active", "joined_at")
    readonly_fields = ("joined_at",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "campaign", "organization", "captain", "is_active", "created_at")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "slug", "captain__username")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("invite_code", "created_at", "updated_at")
    inlines = [TeamMembershipInline]


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("member", "team", "role", "is_active", "joined_at")
    list_filter = ("role", "is_active")
    search_fields = ("member__username", "team__name")
    readonly_fields = ("joined_at",)


@admin.register(TeamReminderLog)
class TeamReminderLogAdmin(admin.ModelAdmin):
    list_display = ("sent_by", "recipient", "team", "sent_at")
    readonly_fields = ("sent_by", "recipient", "team", "message", "sent_at")
    search_fields = ("sent_by__username", "recipient__username", "team__name")

