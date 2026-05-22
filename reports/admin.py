from django.contrib import admin

from .models import ReportExportLog


@admin.register(ReportExportLog)
class ReportExportLogAdmin(admin.ModelAdmin):
    list_display = ("exported_at", "report_key", "report_format", "row_count", "exported_by", "ip_address")
    list_filter = ("report_key", "report_format", "exported_at")
    search_fields = ("report_key", "exported_by__username", "exported_by__email", "ip_address", "user_agent")
