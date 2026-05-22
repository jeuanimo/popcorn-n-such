from __future__ import annotations

from django.conf import settings

from notifications.services import SMTPEmailProvider, TwilioSMSProvider


def get_email_provider():
    provider = (getattr(settings, "EMAIL_PROVIDER", "smtp") or "smtp").lower().strip()
    if provider == "smtp":
        return SMTPEmailProvider()
    # Placeholder: add SendGrid/Mailgun/SES providers later.
    return SMTPEmailProvider()


def get_sms_provider():
    provider = (getattr(settings, "SMS_PROVIDER", "twilio") or "twilio").lower().strip()
    if provider == "twilio":
        return TwilioSMSProvider()
    return TwilioSMSProvider()

