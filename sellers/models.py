from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class SellerLink(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seller_links")
	title = models.CharField(max_length=120)
	slug = models.SlugField(max_length=140)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-created_at"]
		constraints = [
			models.UniqueConstraint(fields=["user", "slug"], name="unique_seller_link_per_user"),
		]

	def __str__(self) -> str:
		return f"{self.user} - {self.title}"


class SellerStore(models.Model):
	"""A seller's personal fundraiser pop-up store page."""

	seller = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="seller_stores",
	)
	team = models.ForeignKey(
		"teams.Team",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="seller_stores",
	)
	campaign = models.ForeignKey(
		"fundraisers.FundraiserCampaign",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="seller_stores",
	)
	slug = models.SlugField(max_length=200, unique=True)
	display_name = models.CharField(max_length=150)
	personal_message = models.TextField(blank=True)
	seller_goal = models.DecimalField(
		max_digits=12,
		decimal_places=2,
		default=0,
		validators=[MinValueValidator(0)],
	)
	profile_photo = models.ImageField(upload_to="sellers/photos/", blank=True, null=True)
	public_seller_link = models.URLField(blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-created_at"]
		constraints = [
			models.UniqueConstraint(fields=["seller", "campaign"], name="unique_store_per_seller_campaign"),
		]

	def __str__(self) -> str:
		return f"{self.display_name} ({self.seller})"
