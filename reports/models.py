from __future__ import annotations

from django.conf import settings
from django.db import models


class ReportFormat(models.TextChoices):
    HTML = "html", "HTML"
    CSV = "csv", "CSV"
    PDF = "pdf", "PDF"


class ReportExportLog(models.Model):
    """
    Audit log of report exports.

    We intentionally keep this record "safe": no sensitive payloads and
    no full customer exports stored here—only metadata about the export.
    """

    report_key = models.CharField(max_length=80, db_index=True)
    report_format = models.CharField(max_length=10, choices=ReportFormat.choices, default=ReportFormat.CSV)
    parameters = models.JSONField(default=dict, blank=True)
    row_count = models.PositiveIntegerField(default=0)

    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_exports",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    exported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-exported_at"]
        indexes = [
            models.Index(fields=["report_key", "exported_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.report_key} ({self.report_format}) at {self.exported_at:%Y-%m-%d %H:%M}"
