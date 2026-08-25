"""
Content-Security-Policy for the storefront.

The checkout page embeds the Poynt Collect iframe, which loads its SDK from
GoDaddy and runs Google reCAPTCHA inside the frame. A restrictive CSP is
valuable precisely on a payment page — it is what stops an injected script from
reading the page or exfiltrating data — but a policy that blocks the card form
breaks checkout entirely.

So the policy ships in **report-only** mode by default. Deploy it, watch the
browser console and any report endpoint for violations, then set
CSP_ENFORCE=true once the checkout page is clean.
"""

from __future__ import annotations

from django.conf import settings

# Origins required by Poynt Collect.
POYNT_SCRIPT_ORIGINS = (
    "https://collect.commerce.godaddy.com",
    "https://collect.commerce.ote-godaddy.com",
    "https://cdn.poynt.net",
)
POYNT_FRAME_ORIGINS = (
    "https://collect.commerce.godaddy.com",
    "https://collect.commerce.ote-godaddy.com",
    "https://cdn.poynt.net",
)
POYNT_CONNECT_ORIGINS = (
    "https://collect.commerce.godaddy.com",
    "https://collect.commerce.ote-godaddy.com",
    "https://services.poynt.net",
    "https://services-ote.poynt.net",
    "https://services-ci.poynt.net",
)
# reCAPTCHA, used by Poynt Collect inside its iframe.
RECAPTCHA_ORIGINS = (
    "https://www.google.com",
    "https://www.gstatic.com",
    "https://www.recaptcha.net",
)
# Bootstrap is loaded from jsDelivr by the base template.
CDN_ORIGINS = ("https://cdn.jsdelivr.net",)


def build_policy() -> str:
    """Assemble the CSP header value."""
    extra = tuple(getattr(settings, "CSP_EXTRA_ORIGINS", ()) or ())

    script_src = ("'self'", "'unsafe-inline'") + POYNT_SCRIPT_ORIGINS + RECAPTCHA_ORIGINS + CDN_ORIGINS + extra
    style_src = ("'self'", "'unsafe-inline'") + CDN_ORIGINS + RECAPTCHA_ORIGINS
    frame_src = ("'self'",) + POYNT_FRAME_ORIGINS + RECAPTCHA_ORIGINS
    connect_src = ("'self'",) + POYNT_CONNECT_ORIGINS + RECAPTCHA_ORIGINS + extra
    img_src = ("'self'", "data:", "https://res.cloudinary.com") + POYNT_SCRIPT_ORIGINS
    font_src = ("'self'", "data:") + CDN_ORIGINS

    directives = {
        "default-src": ("'self'",),
        "script-src": script_src,
        "style-src": style_src,
        "img-src": img_src,
        "font-src": font_src,
        "frame-src": frame_src,
        "connect-src": connect_src,
        # Nothing on this site should be framed by another origin, and no
        # legacy plugin content is ever loaded.
        "frame-ancestors": ("'none'",),
        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        # Card data is posted only to Poynt from inside its own iframe; our own
        # forms must only ever submit back to us.
        "form-action": ("'self'",),
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


class ContentSecurityPolicyMiddleware:
    """
    Attach a CSP header to every response.

    Set CSP_ENFORCE=true to switch from Content-Security-Policy-Report-Only to
    the enforcing header. Verify the checkout page first.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = build_policy()
        self.header = (
            "Content-Security-Policy"
            if getattr(settings, "CSP_ENFORCE", False)
            else "Content-Security-Policy-Report-Only"
        )

    def __call__(self, request):
        response = self.get_response(request)
        # Never clobber a policy set deliberately further up the stack.
        if "Content-Security-Policy" not in response and "Content-Security-Policy-Report-Only" not in response:
            response[self.header] = self.policy
        return response
