from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse

from core.mail import send_runtime_mail
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def send_verification_email(user, request=None):
    token = default_token_generator.make_token(user)
    uid = user.pk
    path = reverse("home") + f"?verify_uid={uid}&token={token}"
    full_url = path
    if request is not None:
        full_url = request.build_absolute_uri(path)

    send_runtime_mail(
        subject="Verify your Popcorn_N_Such account",
        message=f"Verify your account using this link: {full_url}",
        recipient_list=[user.email],
        fail_silently=True,
    )

    log_audit_event(
        action=AuditAction.SECURITY_EVENT,
        message="Verification email dispatched",
        actor=user,
        request=request,
        target=user,
    )
