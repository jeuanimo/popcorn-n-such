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
            name="ReportExportLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_key", models.CharField(db_index=True, max_length=80)),
                (
                    "report_format",
                    models.CharField(
                        choices=[("html", "HTML"), ("csv", "CSV"), ("pdf", "PDF")],
                        default="csv",
                        max_length=10,
                    ),
                ),
                ("parameters", models.JSONField(blank=True, default=dict)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=300)),
                ("exported_at", models.DateTimeField(auto_now_add=True)),
                (
                    "exported_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="report_exports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-exported_at"],
            },
        ),
        migrations.AddIndex(
            model_name="reportexportlog",
            index=models.Index(fields=["report_key", "exported_at"], name="reports_rep_report__3c7e0e_idx"),
        ),
    ]

