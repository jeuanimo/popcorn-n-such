import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
	CUSTOMER = "customer", "Customer"
	SELLER = "seller", "Seller"
	TEAM_CAPTAIN = "team_captain", "Team captain"
	ORGANIZATION_MANAGER = "organization_manager", "Organization manager"
	STAFF = "staff", "Staff"
	ADMIN = "admin", "Admin"


class Role(models.Model):
	key = models.CharField(max_length=32, choices=UserRole.choices, unique=True)
	description = models.CharField(max_length=120, blank=True)

	class Meta:
		ordering = ["key"]

	def __str__(self) -> str:
		return self.get_key_display()


class User(AbstractUser):
	roles = models.ManyToManyField(Role, blank=True, related_name="users")
	phone_number = models.CharField(max_length=25, blank=True)
	is_verified = models.BooleanField(default=False)

	def __str__(self) -> str:
		return self.get_username()

	def has_role(self, role: str) -> bool:
		if role == UserRole.ADMIN and self.is_superuser:
			return True
		if role == UserRole.STAFF and self.is_staff:
			return True
		return self.roles.filter(key=role).exists()

	def has_any_role(self, *roles: str) -> bool:
		return any(self.has_role(role) for role in roles)

	def is_customer(self) -> bool:
		return self.has_role(UserRole.CUSTOMER)

	def is_seller(self) -> bool:
		return self.has_role(UserRole.SELLER)

	def is_team_captain(self) -> bool:
		return self.has_role(UserRole.TEAM_CAPTAIN)

	def is_organization_manager(self) -> bool:
		return self.has_role(UserRole.ORGANIZATION_MANAGER)

	def is_staff_member(self) -> bool:
		return self.has_role(UserRole.STAFF)

	def is_admin_user(self) -> bool:
		return self.has_role(UserRole.ADMIN)


class UserProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
	display_name = models.CharField(max_length=150, blank=True)
	marketing_opt_in = models.BooleanField(default=False)
	sms_opt_in = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return self.display_name or self.user.get_username()


class SavedAddress(models.Model):
	public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_addresses")
	label = models.CharField(max_length=80, default="Home")
	recipient_name = models.CharField(max_length=150)
	phone_number = models.CharField(max_length=25, blank=True)
	address_line_1 = models.CharField(max_length=255)
	address_line_2 = models.CharField(max_length=255, blank=True)
	city = models.CharField(max_length=100)
	state = models.CharField(max_length=100)
	postal_code = models.CharField(max_length=20)
	country = models.CharField(max_length=2, default="US")
	is_default = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-is_default", "label", "created_at"]

	def __str__(self) -> str:
		return f"{self.label} - {self.recipient_name}"


class CustomerProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_profile")
	display_name = models.CharField(max_length=150, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return self.display_name or self.user.get_username()


class NotificationPreference(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preference")
	email_opt_in = models.BooleanField(default=False)
	sms_opt_in = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return f"Notification preferences for {self.user.get_username()}"
