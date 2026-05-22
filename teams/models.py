import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def _default_invite_code():
    return uuid.uuid4().hex


class TeamMemberRole(models.TextChoices):
	MEMBER = "member", "Member"
	CAPTAIN = "captain", "Captain"


class Team(models.Model):
	campaign = models.ForeignKey(
		"fundraisers.FundraiserCampaign",
		on_delete=models.PROTECT,
		related_name="campaign_teams",
		null=True,
		blank=True,
	)
	organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="teams")
	name = models.CharField(max_length=255)
	slug = models.SlugField(max_length=300, unique=True)
	captain = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="captained_teams")
	team_goal = models.DecimalField(
		max_digits=12,
		decimal_places=2,
		default=0,
		validators=[MinValueValidator(0)],
	)
	team_image = models.ImageField(upload_to="teams/images/", blank=True, null=True)
	invite_code = models.CharField(max_length=32, unique=True, default=_default_invite_code)
	public_team_link = models.URLField(blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]

	def __str__(self) -> str:
		return self.name

	def clean(self):
		if self.campaign and self.organization and self.campaign.organization_id != self.organization_id:
			raise ValidationError("Team's organization must match the campaign's organization.")


class TeamMembership(models.Model):
	team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
	member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships")
	role = models.CharField(max_length=20, choices=TeamMemberRole.choices, default=TeamMemberRole.MEMBER)
	is_active = models.BooleanField(default=True)
	joined_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["team__name", "member__username"]
		constraints = [
			models.UniqueConstraint(fields=["team", "member"], name="unique_team_membership"),
		]

	def __str__(self) -> str:
		return f"{self.member} ({self.role}) -> {self.team}"


class TeamReminderLog(models.Model):
	team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="reminder_logs")
	sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_team_reminders")
	recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_team_reminders")
	message = models.TextField()
	sent_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-sent_at"]

	def __str__(self) -> str:
		return f"Reminder from {self.sent_by} to {self.recipient} for {self.team}"
