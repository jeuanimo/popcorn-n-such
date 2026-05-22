from __future__ import annotations

import logging

from .models import AuditLog

logger = logging.getLogger("security_audit")


def log_audit_event(*, action: str, message: str, actor=None, request=None, target=None, metadata=None) -> AuditLog:
    metadata = metadata or {}

    target_model = ""
    target_id = ""
    if target is not None:
        target_model = target._meta.label_lower
        target_id = str(target.pk)

    ip_address = None
    user_agent = ""
    if request is not None:
        ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get(
            "REMOTE_ADDR"
        )
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]

    event = AuditLog.objects.create(
        actor=actor,
        action=action,
        target_model=target_model,
        target_id=target_id,
        message=message[:500],
        metadata=metadata,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info("%s | %s | target=%s:%s", action, message, target_model, target_id)
    return event
