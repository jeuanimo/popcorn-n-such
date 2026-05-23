from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from payments.gateways.registry import get_payment_gateway
from payments.models import PaymentEventLog, PaymentTransaction
from payments.services import record_payment_event


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

