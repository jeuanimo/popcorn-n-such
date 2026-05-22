from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
	ADMIN_ACTION = "admin_action", "Admin action"
	CSV_UPLOAD = "csv_upload", "CSV upload"
	PAYMENT_EVENT = "payment_event", "Payment event"
	LABEL_CREATED = "label_created", "Shipping label created"
	ORDER_STATUS_CHANGE = "order_status_change", "Order status change"
	ROLE_CHANGE = "role_change", "Role change"
	SECURITY_EVENT = "security_event", "Security event"


class AuditLog(models.Model):
	actor = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="audit_events",
	)
	action = models.CharField(max_length=40, choices=AuditAction.choices)
	target_model = models.CharField(max_length=120, blank=True)
	target_id = models.CharField(max_length=64, blank=True)
	message = models.CharField(max_length=500)
	metadata = models.JSONField(default=dict, blank=True)
	ip_address = models.GenericIPAddressField(null=True, blank=True)
	user_agent = models.CharField(max_length=300, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		indexes = [
			models.Index(fields=["action", "created_at"]),
			models.Index(fields=["target_model", "target_id"]),
		]

	def __str__(self) -> str:
		actor = self.actor.get_username() if self.actor else "system"
		return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action} by {actor}"
