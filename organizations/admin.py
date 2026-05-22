from django.contrib import admin

from organizations.models import Organization, OrganizationDocument, OrganizationNote, OrganizationTask
from organizations.services import convert_lead_to_campaign


class OrganizationNoteInline(admin.TabularInline):
	model = OrganizationNote
	extra = 0
	readonly_fields = ("created_at",)


class OrganizationTaskInline(admin.TabularInline):
	model = OrganizationTask
	extra = 0
	readonly_fields = ("created_at", "updated_at")


class OrganizationDocumentInline(admin.TabularInline):
	model = OrganizationDocument
	extra = 0
	readonly_fields = ("uploaded_at",)


@admin.action(description="Convert organization to fundraiser campaign (draft)")
def convert_to_campaign_action(modeladmin, request, queryset):
	converted = 0
	for org in queryset:
		convert_lead_to_campaign(organization=org, actor=request.user, request=request)
		converted += 1
	modeladmin.message_user(request, f"Converted {converted} organization(s) to draft campaigns.")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
	list_display = ("name", "org_type", "lead_status", "is_active", "main_contact", "email", "phone", "relationship_owner", "manager", "updated_at")
	list_filter = ("org_type", "lead_status", "is_active")
	search_fields = ("name", "main_contact", "email", "phone")
	readonly_fields = ("created_at", "updated_at")
	inlines = [OrganizationTaskInline, OrganizationNoteInline, OrganizationDocumentInline]
	actions = [convert_to_campaign_action]


@admin.register(OrganizationTask)
class OrganizationTaskAdmin(admin.ModelAdmin):
	list_display = ("id", "organization", "title", "status", "due_date", "assigned_to", "updated_at")
	list_filter = ("status", "due_date")
	search_fields = ("title", "organization__name", "assigned_to__username")
	readonly_fields = ("created_at", "updated_at")


@admin.register(OrganizationNote)
class OrganizationNoteAdmin(admin.ModelAdmin):
	list_display = ("id", "organization", "created_by", "created_at")
	search_fields = ("organization__name", "note")
	readonly_fields = ("created_at",)


@admin.register(OrganizationDocument)
class OrganizationDocumentAdmin(admin.ModelAdmin):
	list_display = ("id", "organization", "title", "document_type", "uploaded_by", "uploaded_at")
	list_filter = ("document_type", "uploaded_at")
	search_fields = ("organization__name", "title")
	readonly_fields = ("uploaded_at",)
