from django.contrib import admin

from crm.models import CRMActivity, CRMContact, CRMContactTag, CRMNote, CRMTag, CRMTask


class CRMContactTagInline(admin.TabularInline):
	model = CRMContactTag
	extra = 0


class CRMNoteInline(admin.TabularInline):
	model = CRMNote
	extra = 0
	readonly_fields = ("created_at",)


class CRMTaskInline(admin.TabularInline):
	model = CRMTask
	extra = 0
	readonly_fields = ("created_at", "updated_at")


class CRMActivityInline(admin.TabularInline):
	model = CRMActivity
	extra = 0
	readonly_fields = ("occurred_at", "created_at")


@admin.register(CRMContact)
class CRMContactAdmin(admin.ModelAdmin):
	list_display = ("display_name", "relationship_status", "email", "phone", "follow_up_date", "assigned_to", "is_active", "updated_at")
	list_filter = ("relationship_status", "is_active")
	search_fields = ("display_name", "email", "phone", "customer__username", "supplier__name", "organization__name")
	readonly_fields = ("created_at", "updated_at")
	inlines = [CRMContactTagInline, CRMTaskInline, CRMNoteInline, CRMActivityInline]


@admin.register(CRMTag)
class CRMTagAdmin(admin.ModelAdmin):
	list_display = ("name", "color", "created_at")
	search_fields = ("name",)


@admin.register(CRMNote)
class CRMNoteAdmin(admin.ModelAdmin):
	list_display = ("id", "contact", "is_sensitive", "created_by", "created_at")
	list_filter = ("is_sensitive", "created_at")
	search_fields = ("contact__display_name", "note")
	readonly_fields = ("created_at",)


@admin.register(CRMTask)
class CRMTaskAdmin(admin.ModelAdmin):
	list_display = ("id", "contact", "title", "status", "due_date", "follow_up_date", "assigned_to", "updated_at")
	list_filter = ("status", "due_date")
	search_fields = ("title", "contact__display_name", "assigned_to__username")
	readonly_fields = ("created_at", "updated_at")


@admin.register(CRMActivity)
class CRMActivityAdmin(admin.ModelAdmin):
	list_display = ("id", "contact", "activity_type", "summary", "occurred_at", "created_at")
	list_filter = ("activity_type", "occurred_at")
	search_fields = ("summary", "contact__display_name")
	readonly_fields = ("created_at",)
