from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.validators import validate_json_dict


class CRMRelationshipStatus(models.TextChoices):
    LEAD = "lead", "Lead"
    ACTIVE = "active", "Active"
    PAST = "past", "Past"
    DORMANT = "dormant", "Dormant"
    DO_NOT_CONTACT = "do_not_contact", "Do Not Contact"


class CRMTaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class CRMContact(models.Model):
    """
    General CRM contact that can optionally link to:
    - Customer (`accounts.User`)
    - Supplier (`suppliers.Supplier`)
    - Organization (`organizations.Organization`)
    """

    display_name = models.CharField(max_length=200)
    relationship_status = models.CharField(
        max_length=20, choices=CRMRelationshipStatus.choices, default=CRMRelationshipStatus.LEAD
    )

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)

    follow_up_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_crm_contacts",
    )

    customer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_contact",
    )
    supplier = models.OneToOneField(
        "suppliers.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_contact",
    )
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_contact",
    )

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_crm_contacts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["relationship_status", "follow_up_date"]),
        ]

    def __str__(self) -> str:
        return self.display_name


class CRMTag(models.Model):
    name = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=20, blank=True, help_text="Optional CSS color name/hex.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CRMContactTag(models.Model):
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="tag_links")
    tag = models.ForeignKey(CRMTag, on_delete=models.CASCADE, related_name="contact_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["contact", "tag"], name="unique_contact_tag"),
        ]

    def __str__(self) -> str:
        return f"{self.contact} -> {self.tag}"


class CRMNote(models.Model):
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="crm_notes")
    note = models.TextField()
    is_sensitive = models.BooleanField(default=True, help_text="Internal note; never shown to customers.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Note for {self.contact} ({self.created_at:%Y-%m-%d})"


class CRMTask(models.Model):
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="crm_tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=CRMTaskStatus.choices, default=CRMTaskStatus.OPEN)
    due_date = models.DateField(null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_tasks_assigned",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_tasks_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "-created_at"]
        indexes = [
            models.Index(fields=["status", "due_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.contact})"


class CRMActivity(models.Model):
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=60)
    summary = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True, validators=[validate_json_dict])
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crm_activities",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["activity_type", "occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.activity_type}: {self.summary}"
