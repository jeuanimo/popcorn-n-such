from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class FundraiserInvite(models.Model):
	code = models.CharField(max_length=32, unique=True)
	campaign_name = models.CharField(max_length=150)
	team_name = models.CharField(max_length=120, blank=True)
	seller_name = models.CharField(max_length=120, blank=True)
	is_active = models.BooleanField(default=True)
	expires_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["campaign_name", "code"]

	def __str__(self) -> str:
		return f"{self.campaign_name} ({self.code})"

	@property
	def is_valid(self) -> bool:
		if not self.is_active:
			return False
		if self.expires_at and self.expires_at <= timezone.now():
			return False
		return True


class FundraiserParticipation(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fundraiser_participations")
	invite = models.ForeignKey(FundraiserInvite, on_delete=models.PROTECT, related_name="participants")
	joined_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-joined_at"]
		constraints = [
			models.UniqueConstraint(fields=["user", "invite"], name="unique_fundraiser_participation"),
		]

	def __str__(self) -> str:
		return f"{self.user} in {self.invite}"


class FundraiserRequestStatus(models.TextChoices):
	PENDING = "pending", "Pending"
	APPROVED = "approved", "Approved"
	DECLINED = "declined", "Declined"


class FundraiserRequest(models.Model):
	# Contact — user account is linked after staff provisions the account
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="fundraiser_requests")
	contact_first_name = models.CharField(max_length=80, default="")
	contact_last_name = models.CharField(max_length=80, default="")
	contact_email = models.EmailField(default="")
	contact_phone = models.CharField(max_length=30, blank=True)

	# Organization
	organization_name = models.CharField(max_length=180)
	org_type = models.CharField(max_length=40, default="school")
	estimated_sellers = models.PositiveIntegerField(default=1)

	# Campaign intent
	goal_description = models.TextField(blank=True)
	fundraising_purpose = models.TextField(blank=True)
	desired_start_date = models.DateField(null=True, blank=True)
	goal_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

	status = models.CharField(max_length=20, choices=FundraiserRequestStatus.choices, default=FundraiserRequestStatus.PENDING)
	staff_notes = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self) -> str:
		return f"{self.organization_name} — {self.contact_email}"


class FundraiserCampaignStatus(models.TextChoices):
	DRAFT = "draft", "Draft"
	SCHEDULED = "scheduled", "Scheduled"
	ACTIVE = "active", "Active"
	CLOSED = "closed", "Closed"
	PAID_OUT = "paid_out", "Paid out"


class FundraiserCampaign(models.Model):
	organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="fundraiser_campaigns")
	campaign_name = models.CharField(max_length=180)
	slug = models.SlugField(max_length=220, unique=True)
	description = models.TextField(blank=True)
	fundraising_purpose = models.TextField(blank=True)
	start_date = models.DateField()
	end_date = models.DateField()
	goal_amount = models.DecimalField(max_digits=12, decimal_places=2)
	status = models.CharField(max_length=20, choices=FundraiserCampaignStatus.choices, default=FundraiserCampaignStatus.DRAFT)
	profit_percentage = models.DecimalField(
		max_digits=5,
		decimal_places=2,
		default=30,
		validators=[MinValueValidator(0), MaxValueValidator(100)],
	)
	campaign_image = models.ImageField(upload_to="fundraisers/images/", blank=True, null=True)
	campaign_banner = models.ImageField(upload_to="fundraisers/banners/", blank=True, null=True)
	public_campaign_link = models.URLField(blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_fundraiser_campaigns")
	approved_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name="approved_fundraiser_campaigns",
	)
	is_active = models.BooleanField(default=True)
	teams = models.ManyToManyField("teams.Team", blank=True, related_name="fundraiser_campaigns")
	sellers = models.ManyToManyField("sellers.SellerLink", blank=True, related_name="fundraiser_campaigns")
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-start_date", "campaign_name"]

	def __str__(self) -> str:
		return self.campaign_name

	def clean(self):
		if self.end_date < self.start_date:
			raise ValidationError("Campaign end date must be on or after the start date.")

	def is_accepting_orders(self, *, as_of=None) -> bool:
		if not self.is_active:
			return False
		if self.status != FundraiserCampaignStatus.ACTIVE:
			return False

		today = as_of or timezone.localdate()
		if today < self.start_date:
			return False
		if today > self.end_date:
			return False
		return True

	def goal_progress_percent(self, total_sales_cents: int) -> int:
		if self.goal_amount <= 0:
			return 0
		goal_cents = int(self.goal_amount * 100)
		if goal_cents <= 0:
			return 0
		progress = int((total_sales_cents / goal_cents) * 100)
		return max(0, min(100, progress))
