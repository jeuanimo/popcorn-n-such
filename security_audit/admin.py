from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
	list_display = ("created_at", "action", "actor", "target_model", "target_id")
	list_filter = ("action", "created_at")
	search_fields = ("message", "target_model", "target_id", "actor__username", "actor__email")
	readonly_fields = (
		"actor",
		"action",
		"target_model",
		"target_id",
		"message",
		"metadata",
		"ip_address",
		"user_agent",
		"created_at",
	)

	def has_add_permission(self, request):
		return False
