"""
One-time Poynt merchant OAuth authorization callback.

Captures a merchant's businessId during onboarding, via the redirect Poynt
sends after https://poynt.net/applications/authorize?... . This is a
provisioning endpoint, not part of checkout — see docs/PAYMENTS.md.

Disabled by default (POYNT_AUTHORIZE_CALLBACK_ENABLED). The claims decoded
from the "code" JWT (application id, business id) are logged for an operator
to read from the server logs and are never rendered into the response.
"""

from __future__ import annotations

import logging

import jwt
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_GET

logger = logging.getLogger("payments.authorize")

_POYNT_ISSUER = "https://poynt.net"
_TEMPLATE = "payments/poynt_authorized.html"


@require_GET
def poynt_authorize_callback(request: HttpRequest) -> HttpResponse:
    if not getattr(settings, "POYNT_AUTHORIZE_CALLBACK_ENABLED", False):
        return HttpResponseForbidden("Not found.")

    code = (request.GET.get("code") or "").strip()
    status = (request.GET.get("status") or "").strip()
    context = (request.GET.get("context") or "").strip()

    if not code:
        logger.warning(
            "Poynt authorization callback: no code in the query string (status=%s, context=%s)",
            status or "(none)",
            context or "(none)",
        )
        return render(request, _TEMPLATE, {"ok": False}, status=400)

    public_key = (getattr(settings, "POYNT_PLATFORM_PUBLIC_KEY", "") or "").strip()
    verified = bool(public_key)
    try:
        if verified:
            claims = jwt.decode(
                code,
                public_key,
                algorithms=["RS256"],
                issuer=_POYNT_ISSUER,
                options={"verify_aud": False},
            )
        else:
            claims = jwt.decode(
                code,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_iss": False,
                    "verify_aud": False,
                },
            )
    except jwt.PyJWTError as exc:
        logger.error(
            "Poynt authorization callback: could not decode the code JWT (%s), "
            "verified=%s, status=%s, context=%s",
            type(exc).__name__,
            verified,
            status or "(none)",
            context or "(none)",
        )
        return render(request, _TEMPLATE, {"ok": False}, status=400)

    application_id = str(claims.get("sub") or "(none)")
    business_id = str(claims.get("poynt.biz") or "(none)")

    # The only place these claims are recorded. Never put them in the
    # response — the operator reads them from here.
    logger.info(
        "Poynt authorization callback: status=%s verified=%s application_id=%s business_id=%s context=%s",
        status or "(none)",
        verified,
        application_id,
        business_id,
        context or "(none)",
    )

    return render(request, _TEMPLATE, {"ok": True})
