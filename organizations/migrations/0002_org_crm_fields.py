from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="org_type",
            field=models.CharField(
                choices=[
                    ("school", "School"),
                    ("church", "Church"),
                    ("sports_team", "Sports team"),
                    ("fraternity_sorority", "Fraternity/sorority"),
                    ("youth_group", "Youth group"),
                    ("nonprofit", "Nonprofit"),
                    ("corporate_buyer", "Corporate buyer"),
                    ("event_planner", "Event planner"),
                    ("wholesale_customer", "Repeat wholesale customer"),
                ],
                default="school",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="lead_status",
            field=models.CharField(
                choices=[
                    ("new_lead", "New Lead"),
                    ("contacted", "Contacted"),
                    ("interested", "Interested"),
                    ("proposal_sent", "Proposal Sent"),
                    ("active_fundraiser", "Active Fundraiser"),
                    ("past_customer", "Past Customer"),
                    ("dormant", "Dormant"),
                    ("do_not_contact", "Do Not Contact"),
                ],
                default="new_lead",
                max_length=30,
            ),
        ),
        migrations.AddField(model_name="organization", name="is_active", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="organization", name="main_contact", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="organization", name="email", field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name="organization", name="phone", field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name="organization", name="website", field=models.URLField(blank=True)),
        migrations.AddField(model_name="organization", name="address_line_1", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="organization", name="address_line_2", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="organization", name="city", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="organization", name="state", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="organization", name="postal_code", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="organization", name="country", field=models.CharField(default="US", max_length=2)),
        migrations.AddField(model_name="organization", name="notes", field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="organization",
            name="relationship_owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Internal owner responsible for the relationship.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="owned_organizations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(model_name="organization", name="last_contact_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="organization", name="next_contact_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="organization", name="total_sales_cents", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(
            model_name="organization",
            name="total_fundraiser_revenue_cents",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="OrganizationNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("note", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="organization_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crm_notes",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OrganizationTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("open", "Open"), ("done", "Done"), ("cancelled", "Cancelled")], default="open", max_length=12)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_organization_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_organization_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crm_tasks",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["status", "due_date", "-created_at"],
                "indexes": [models.Index(fields=["status", "due_date"], name="organizations_task_status_due_idx")],
            },
        ),
        migrations.CreateModel(
            name="OrganizationDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("file", models.FileField(upload_to="organizations/documents/%Y/%m/%d/")),
                ("document_type", models.CharField(blank=True, help_text="e.g. contract, W-9, proposal.", max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="organizations.organization",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_organization_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-uploaded_at"]},
        ),
    ]

