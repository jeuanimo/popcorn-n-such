from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("organizations", "0002_org_crm_fields"),
        ("suppliers", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CRMContact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=200)),
                (
                    "relationship_status",
                    models.CharField(
                        choices=[
                            ("lead", "Lead"),
                            ("active", "Active"),
                            ("past", "Past"),
                            ("dormant", "Dormant"),
                            ("do_not_contact", "Do Not Contact"),
                        ],
                        default="lead",
                        max_length=20,
                    ),
                ),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("follow_up_date", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_crm_contacts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_crm_contacts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_contact",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_contact",
                        to="organizations.organization",
                    ),
                ),
                (
                    "supplier",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_contact",
                        to="suppliers.supplier",
                    ),
                ),
            ],
            options={
                "ordering": ["display_name"],
                "indexes": [models.Index(fields=["relationship_status", "follow_up_date"], name="crm_contact_status_follow_idx")],
            },
        ),
        migrations.CreateModel(
            name="CRMTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("color", models.CharField(blank=True, help_text="Optional CSS color name/hex.", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="CRMActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("activity_type", models.CharField(max_length=60)),
                ("summary", models.CharField(max_length=255)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(db_index=True, default=timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contact",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="crm.crmcontact"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_activities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at"],
                "indexes": [models.Index(fields=["activity_type", "occurred_at"], name="crm_activity_type_time_idx")],
            },
        ),
        migrations.CreateModel(
            name="CRMNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.TextField()),
                ("is_sensitive", models.BooleanField(default=True, help_text="Internal note; never shown to customers.")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "contact",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crm_notes", to="crm.crmcontact"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CRMTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Open"), ("in_progress", "In progress"), ("completed", "Completed"), ("canceled", "Canceled")],
                        default="open",
                        max_length=12,
                    ),
                ),
                ("due_date", models.DateField(blank=True, null=True)),
                ("follow_up_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_tasks_assigned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crm_tasks", to="crm.crmcontact"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crm_tasks_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["status", "due_date", "-created_at"],
                "indexes": [models.Index(fields=["status", "due_date"], name="crm_task_status_due_idx")],
            },
        ),
        migrations.CreateModel(
            name="CRMContactTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contact",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tag_links", to="crm.crmcontact"),
                ),
                (
                    "tag",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_links", to="crm.crmtag"),
                ),
            ],
            options={},
        ),
        migrations.AddConstraint(
            model_name="crmcontacttag",
            constraint=models.UniqueConstraint(fields=("contact", "tag"), name="unique_contact_tag"),
        ),
    ]

