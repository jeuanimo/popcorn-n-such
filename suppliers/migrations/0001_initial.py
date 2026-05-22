from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("ingredients", "Ingredients"),
                            ("packaging", "Packaging"),
                            ("shipping_supplies", "Shipping supplies"),
                            ("equipment", "Equipment"),
                            ("marketing", "Marketing"),
                            ("technology", "Technology"),
                            ("payment_services", "Payment services"),
                            ("maintenance", "Maintenance"),
                            ("wholesale_food_distributor", "Wholesale food distributor"),
                        ],
                        max_length=40,
                    ),
                ),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive")], default="active", max_length=12)),
                ("contact_person", models.CharField(blank=True, max_length=150)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("website", models.URLField(blank=True)),
                ("address_line_1", models.CharField(blank=True, max_length=255)),
                ("address_line_2", models.CharField(blank=True, max_length=255)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("postal_code", models.CharField(blank=True, max_length=20)),
                ("country", models.CharField(default="US", max_length=2)),
                ("products_supplies_provided", models.TextField(blank=True, help_text="High-level description of products/supplies provided.")),
                ("payment_terms", models.CharField(blank=True, help_text="e.g. Net 30, prepaid, COD.", max_length=120)),
                ("average_lead_time_days", models.PositiveIntegerField(default=0)),
                ("vendor_tax_id", models.CharField(blank=True, help_text="Optional vendor/tax ID.", max_length=80)),
                ("rating", models.PositiveSmallIntegerField(default=0, help_text="0-5 internal rating.")),
                ("notes", models.TextField(blank=True)),
                ("last_contact_date", models.DateField(blank=True, null=True)),
                ("next_follow_up_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_suppliers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [models.Index(fields=["category", "status"], name="suppliers_sup_category_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="SupplierDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("file", models.FileField(upload_to="suppliers/documents/%Y/%m/%d/")),
                ("document_type", models.CharField(blank=True, help_text="e.g. contract, W-9, spec sheet.", max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "supplier",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="suppliers.supplier"),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_supplier_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-uploaded_at"]},
        ),
        migrations.CreateModel(
            name="SupplierNote",
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
                        related_name="supplier_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crm_notes", to="suppliers.supplier"),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="SupplierPerformanceNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating_delta", models.SmallIntegerField(default=0, help_text="Optional +/- rating adjustment context.")),
                ("note", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="supplier_performance_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_notes",
                        to="suppliers.supplier",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="SupplierTask",
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
                        related_name="assigned_supplier_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_supplier_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crm_tasks", to="suppliers.supplier"),
                ),
            ],
            options={
                "ordering": ["status", "due_date", "-created_at"],
                "indexes": [models.Index(fields=["status", "due_date"], name="suppliers_task_status_due_idx")],
            },
        ),
        migrations.CreateModel(
            name="SupplierPurchaseOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("po_number", models.CharField(max_length=60, unique=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("sent", "Sent"), ("confirmed", "Confirmed"), ("received", "Received"), ("cancelled", "Cancelled")], default="draft", max_length=12)),
                ("payment_terms", models.CharField(blank=True, max_length=120)),
                ("expected_delivery_date", models.DateField(blank=True, null=True)),
                ("received_date", models.DateField(blank=True, null=True)),
                ("total_cents", models.PositiveIntegerField(default=0)),
                ("currency", models.CharField(default="USD", max_length=10)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_supplier_purchase_orders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="suppliers.supplier"),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["supplier", "status"], name="suppliers_po_supplier_status_idx")],
            },
        ),
    ]

