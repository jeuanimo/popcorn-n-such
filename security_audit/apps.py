from django.apps import AppConfig


class SecurityAuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security_audit"

    def ready(self):
        import security_audit.signals  # noqa: F401
