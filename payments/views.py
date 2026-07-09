from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentEventLog, PaymentTransaction
from payments.services import record_payment_event
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def _header_dict(request: HttpRequest) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        try:
            headers[str(key)] = str(value)
        except Exception:
            continue
    return headers


def payment_webhook(request: HttpRequest, provider: str) -> HttpResponse:
    gateway = get_payment_gateway(provider)
    body = request.body or b""
    headers = _header_dict(request)

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        payload = {}

    signature_valid = gateway.verify_webhook_signature(body=body, headers=headers)
    ids = gateway.extract_provider_ids_from_webhook(payload=payload)
    event_type = str(payload.get("type") or payload.get("event_type") or "webhook").strip()
    external_event_id = str(ids.get("event_id") or payload.get("id") or "").strip()
    request_id = str(headers.get("X-Request-Id", "") or headers.get("X-Request-ID", "")).strip()

    tx = None
    provider_transaction_id = ids.get("provider_transaction_id", "")
    provider_session_id = ids.get("provider_session_id", "")
    if provider_transaction_id:
        tx = PaymentTransaction.objects.filter(provider=gateway.slug, provider_transaction_id=provider_transaction_id).first()
    if not tx and provider_session_id:
        tx = PaymentTransaction.objects.filter(provider=gateway.slug, provider_session_id=provider_session_id).first()

    event = record_payment_event(
        provider=gateway.slug,
        event_type=event_type,
        payload=payload,
        headers=headers,
        signature_valid=signature_valid,
        transaction_obj=tx,
        external_event_id=external_event_id,
        request_id=request_id,
    )

    # Placeholder processing hook: store event as received; provider-specific handlers can
    # later dispatch verification and call handle_payment_success/failure.
    PaymentEventLog.objects.filter(id=event.id).update(processed_at=timezone.now())

    return JsonResponse({"ok": True, "signature_valid": signature_valid})


@require_POST
def collect_telemetry(request: HttpRequest) -> HttpResponse:
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    event_name = str(payload.get("event") or "").strip().lower()
    allowed_events = {"ready", "error", "nonce", "iframe_height_change", "sdk_load_error"}
    if event_name not in allowed_events:
        return JsonResponse({"ok": False, "error": "invalid_event"}, status=400)

    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    allowed_detail_keys = {
        "code",
        "requestId",
        "source",
        "type",
        "height",
        "hasNonce",
        "recaptchaType",
        "chargeSource",
    }
    sanitized_details = {
        key: str(details.get(key))[:120]
        for key in allowed_detail_keys
        if details.get(key) not in (None, "")
    }

    actor = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    log_audit_event(
        action=AuditAction.PAYMENT_EVENT,
        message=f"Poynt Collect event listener: {event_name}",
        actor=actor,
        request=request,
        metadata={
            "provider": "godaddy",
            "collect_event": event_name,
            "details": sanitized_details,
        },
    )
    return JsonResponse({"ok": True})

