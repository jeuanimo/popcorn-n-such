import hashlib

from django.db import models
from django.utils import timezone


class RecoveryStage(models.TextChoices):
	FIRST = "first", "First reminder"
	SECOND = "second", "Second reminder"
	FINAL = "final", "Final reminder"


class MessageChannel(models.TextChoices):
	EMAIL = "email", "Email"
	SMS = "sms", "SMS"


class MessageStatus(models.TextChoices):
	SENT = "sent", "Sent"
	FAILED = "failed", "Failed"
	SKIPPED = "skipped", "Skipped"


class EventCloseReason(models.TextChoices):
	RECOVERED = "recovered", "Recovered"
	EMPTIED = "emptied", "Emptied"
	EXPIRED = "expired", "Expired"
	UNSUBSCRIBED = "unsubscribed", "Unsubscribed"


class TokenPurpose(models.TextChoices):
	RECOVER = "recover", "Recover cart"
	UNSUBSCRIBE = "unsubscribe", "Unsubscribe"


class AbandonedCartEvent(models.Model):
	cart = models.OneToOneField("cart.Cart", on_delete=models.CASCADE, related_name="abandoned_event")
	customer_email = models.EmailField(blank=True)
	customer_phone = models.CharField(max_length=25, blank=True)
	sms_consent = models.BooleanField(default=False)
	email_unsubscribed = models.BooleanField(default=False)
	sms_opted_out = models.BooleanField(default=False)

	abandoned_at = models.DateTimeField(db_index=True)
	last_activity_at = models.DateTimeField(db_index=True)
	expires_at = models.DateTimeField(db_index=True)

	first_reminder_sent_at = models.DateTimeField(null=True, blank=True)
	second_reminder_sent_at = models.DateTimeField(null=True, blank=True)
	final_reminder_sent_at = models.DateTimeField(null=True, blank=True)

	fundraiser_campaign = models.CharField(max_length=120, blank=True)
	fundraiser_team = models.CharField(max_length=120, blank=True)
	fundraiser_seller = models.CharField(max_length=120, blank=True)

	recovered = models.BooleanField(default=False)
	recovered_at = models.DateTimeField(null=True, blank=True)
	recovered_order = models.ForeignKey(
		"orders.Order",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="recovered_cart_events",
	)

	is_closed = models.BooleanField(default=False, db_index=True)
	close_reason = models.CharField(max_length=20, choices=EventCloseReason.choices, blank=True)
	closed_at = models.DateTimeField(null=True, blank=True)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-updated_at"]

	def __str__(self) -> str:
		return f"Abandoned event for cart #{self.cart_id}"

	def mark_stage_sent(self, stage: str, when=None):
		when = when or timezone.now()
		if stage == RecoveryStage.FIRST:
			self.first_reminder_sent_at = when
		elif stage == RecoveryStage.SECOND:
			self.second_reminder_sent_at = when
		elif stage == RecoveryStage.FINAL:
			self.final_reminder_sent_at = when

	def close(self, *, reason: str, when=None):
		when = when or timezone.now()
		self.is_closed = True
		self.close_reason = reason
		self.closed_at = when


class CartRecoveryMessage(models.Model):
	event = models.ForeignKey(AbandonedCartEvent, on_delete=models.CASCADE, related_name="messages")
	stage = models.CharField(max_length=10, choices=RecoveryStage.choices)
	channel = models.CharField(max_length=10, choices=MessageChannel.choices)
	status = models.CharField(max_length=10, choices=MessageStatus.choices)
	to_value = models.CharField(max_length=254, blank=True)
	subject = models.CharField(max_length=200, blank=True)
	body = models.TextField(blank=True)
	provider_response = models.JSONField(default=dict, blank=True)
	failure_reason = models.CharField(max_length=250, blank=True)
	sent_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		constraints = [
			models.UniqueConstraint(fields=["event", "stage", "channel"], name="unique_recovery_message_per_stage"),
		]

	def __str__(self) -> str:
		return f"{self.channel} {self.stage} for event #{self.event_id}"


class CartRecoveryToken(models.Model):
	cart = models.ForeignKey("cart.Cart", on_delete=models.CASCADE, related_name="recovery_tokens")
	event = models.ForeignKey(AbandonedCartEvent, on_delete=models.CASCADE, related_name="tokens")
	purpose = models.CharField(max_length=20, choices=TokenPurpose.choices)
	token_hash = models.CharField(max_length=64, unique=True)
	expires_at = models.DateTimeField(db_index=True)
	used_at = models.DateTimeField(null=True, blank=True)
	revoked_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		indexes = [models.Index(fields=["purpose", "expires_at"])]

	def __str__(self) -> str:
		return f"{self.purpose} token for cart #{self.cart_id}"

	@staticmethod
	def hash_raw_token(raw_token: str) -> str:
		return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

	@property
	def is_usable(self) -> bool:
		if self.used_at or self.revoked_at:
			return False
		return timezone.now() < self.expires_at
