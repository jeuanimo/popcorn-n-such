from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Role, SavedAddress, User, UserProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
	fieldsets = BaseUserAdmin.fieldsets + (
		(
			"Popcorn N Such",
			{
				"fields": (
					"roles",
					"phone_number",
					"is_verified",
				)
			},
		),
	)
	list_display = (
		"username",
		"email",
		"role_list",
		"is_staff",
		"is_active",
	)
	list_filter = ("roles", "is_staff", "is_active")

	def role_list(self, obj):
		return ", ".join(obj.roles.values_list("key", flat=True))

	role_list.short_description = "Roles"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ("user", "display_name", "marketing_opt_in", "sms_opt_in")
	search_fields = ("user__username", "user__email", "display_name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
	list_display = ("key", "description")
	search_fields = ("key", "description")


@admin.register(SavedAddress)
class SavedAddressAdmin(admin.ModelAdmin):
	list_display = ("public_id", "user", "label", "city", "state", "country", "is_default")
	search_fields = ("public_id", "user__username", "user__email", "label", "recipient_name")
	list_filter = ("country", "is_default")
