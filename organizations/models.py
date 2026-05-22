from __future__ import annotations

from django.conf import settings
from django.db import models


class OrganizationType(models.TextChoices):
    SCHOOL = "school", "School"
    CHURCH = "church", "Church"
    SPORTS_TEAM = "sports_team", "Sports team"
    FRAT_SORORITY = "fraternity_sorority", "Fraternity/sorority"
    YOUTH_GROUP = "youth_group", "Youth group"
    NONPROFIT = "nonprofit", "Nonprofit"
    CORPORATE_BUYER = "corporate_buyer", "Corporate buyer"
    EVENT_PLANNER = "event_planner", "Event planner"
    WHOLESALE_CUSTOMER = "wholesale_customer", "Repeat wholesale customer"


class LeadStatus(models.TextChoices):
    NEW_LEAD = "new_lead", "New Lead"
    CONTACTED = "contacted", "Contacted"
    INTERESTED = "interested", "Interested"
    PROPOSAL_SENT = "proposal_sent", "Proposal Sent"
    ACTIVE_FUNDRAISER = "active_fundraiser", "Active Fundraiser"
    PAST_CUSTOMER = "past_customer", "Past Customer"
    DORMANT = "dormant", "Dormant"
    DO_NOT_CONTACT = "do_not_contact", "Do Not Contact"


class Organization(models.Model):
	name = models.CharField(max_length=255)
	org_type = models.CharField(max_length=40, choices=OrganizationType.choices, default=OrganizationType.SCHOOL)
	lead_status = models.CharField(max_length=30, choices=LeadStatus.choices, default=LeadStatus.NEW_LEAD)
	is_active = models.BooleanField(default=True)

	main_contact = models.CharField(max_length=150, blank=True)
	email = models.EmailField(blank=True)
	phone = models.CharField(max_length=30, blank=True)
	website = models.URLField(blank=True)

	address_line_1 = models.CharField(max_length=255, blank=True)
	address_line_2 = models.CharField(max_length=255, blank=True)
	city = models.CharField(max_length=100, blank=True)
	state = models.CharField(max_length=100, blank=True)
	postal_code = models.CharField(max_length=20, blank=True)
	country = models.CharField(max_length=2, default="US")

	notes = models.TextField(blank=True)

	relationship_owner = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="owned_organizations",
		help_text="Internal owner responsible for the relationship.",
	)

	manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="managed_organizations")

	last_contact_date = models.DateField(null=True, blank=True)
	next_contact_date = models.DateField(null=True, blank=True)

	total_sales_cents = models.PositiveIntegerField(default=0)
	total_fundraiser_revenue_cents = models.PositiveIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self) -> str:
		return self.name


class OrganizationNote(models.Model):
	organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="crm_notes")
	note = models.TextField()
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="organization_notes",
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self) -> str:
		return f"Note for {self.organization} ({self.created_at:%Y-%m-%d})"


class OrganizationTaskStatus(models.TextChoices):
	OPEN = "open", "Open"
	DONE = "done", "Done"
	CANCELLED = "cancelled", "Cancelled"


class OrganizationTask(models.Model):
	organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="crm_tasks")
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	status = models.CharField(max_length=12, choices=OrganizationTaskStatus.choices, default=OrganizationTaskStatus.OPEN)
	due_date = models.DateField(null=True, blank=True)
	assigned_to = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="assigned_organization_tasks",
	)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="created_organization_tasks",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["status", "due_date", "-created_at"]
		indexes = [
			models.Index(fields=["status", "due_date"]),
		]

	def __str__(self) -> str:
		return f"{self.title} ({self.organization})"


class OrganizationDocument(models.Model):
	organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
	title = models.CharField(max_length=200)
	file = models.FileField(upload_to="organizations/documents/%Y/%m/%d/")
	document_type = models.CharField(max_length=80, blank=True, help_text="e.g. contract, W-9, proposal.")
	notes = models.TextField(blank=True)

	uploaded_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="uploaded_organization_documents",
	)
	uploaded_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-uploaded_at"]

	def __str__(self) -> str:
		return f"{self.title} ({self.organization})"
