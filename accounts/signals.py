from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerProfile, NotificationPreference, Role, User, UserProfile, UserRole
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


@receiver(post_save, sender=User)
def create_user_profile(sender, instance: User, created: bool, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
        CustomerProfile.objects.create(user=instance)
        NotificationPreference.objects.create(user=instance)
        default_role, _ = Role.objects.get_or_create(key=UserRole.CUSTOMER)
        instance.roles.add(default_role)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance: User, **kwargs):
    if hasattr(instance, "profile"):
        instance.profile.save()

    customer_profile, _ = CustomerProfile.objects.get_or_create(user=instance)
    notification_preference, _ = NotificationPreference.objects.get_or_create(user=instance)

    if customer_profile.display_name != instance.profile.display_name:
        customer_profile.display_name = instance.profile.display_name
        customer_profile.save(update_fields=["display_name", "updated_at"])

    profile_email_opt_in = instance.profile.marketing_opt_in
    profile_sms_opt_in = instance.profile.sms_opt_in
    if (
        notification_preference.email_opt_in != profile_email_opt_in
        or notification_preference.sms_opt_in != profile_sms_opt_in
    ):
        notification_preference.email_opt_in = profile_email_opt_in
        notification_preference.sms_opt_in = profile_sms_opt_in
        notification_preference.save(update_fields=["email_opt_in", "sms_opt_in", "updated_at"])


@receiver(m2m_changed, sender=User.roles.through)
def audit_role_changes(sender, instance: User, action: str, pk_set, **kwargs):
    if action not in {"post_add", "post_remove", "post_clear"}:
        return

    role_keys = list(Role.objects.filter(pk__in=pk_set).values_list("key", flat=True)) if pk_set else []
    log_audit_event(
        action=AuditAction.ROLE_CHANGE,
        message=f"Roles updated via {action}",
        actor=instance,
        target=instance,
        metadata={"action": action, "roles": role_keys},
    )


@receiver(user_login_failed)
def track_failed_login(sender, credentials, request, **kwargs):
    identifier = credentials.get("username", "unknown")
    key = f"auth:failed:{identifier}"
    failures = cache.get(key, 0) + 1
    cache.set(key, failures, timeout=getattr(settings, "LOGIN_THROTTLE_WINDOW_SECONDS", 900))

    if failures >= getattr(settings, "LOGIN_THROTTLE_LIMIT", 5):
        log_audit_event(
            action=AuditAction.SECURITY_EVENT,
            message="Login throttling threshold reached",
            request=request,
            metadata={"username": identifier, "failures": failures},
        )


@receiver(user_logged_in)
def clear_failed_logins(sender, user, request, **kwargs):
    cache.delete(f"auth:failed:{user.get_username()}")
