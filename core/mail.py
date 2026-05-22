from __future__ import annotations

from django.conf import settings
from django.core.mail import get_connection, send_mail

from core.runtime_settings import get_runtime_setting


def send_runtime_mail(*, subject: str, message: str, recipient_list: list[str], fail_silently: bool = True):
    host = get_runtime_setting("email_host", settings.EMAIL_HOST)
    port = int(get_runtime_setting("email_port", settings.EMAIL_PORT) or settings.EMAIL_PORT)
    username = get_runtime_setting("email_host_user", settings.EMAIL_HOST_USER)
    password = get_runtime_setting("email_host_password", settings.EMAIL_HOST_PASSWORD)
    use_tls = bool(get_runtime_setting("email_use_tls", settings.EMAIL_USE_TLS))
    from_email = get_runtime_setting("default_from_email", settings.DEFAULT_FROM_EMAIL)

    connection = get_connection(
        host=host,
        port=port,
        username=username,
        password=password,
        use_tls=use_tls,
        fail_silently=fail_silently,
    )
    return send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
        fail_silently=fail_silently,
        connection=connection,
    )
