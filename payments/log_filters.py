"""
Logging safeguards for payment code.

Two jobs:

  * `PaymentContextFormatter` appends the structured fields we actually want on
    a payment log line (order, payment, transaction, provider, status, amount).
  * `RedactSensitiveFilter` is a last line of defence. Payment code is written
    not to log card data, access tokens or private keys in the first place —
    this filter exists so that a future careless log call cannot leak one.

Nothing here is a substitute for not logging secrets. It is a backstop.
"""

from __future__ import annotations

import logging
import re

#: Fields copied onto the log line when present on the record.
CONTEXT_FIELDS = (
    "order_id",
    "payment_id",
    "transaction_id",
    "provider",
    "status",
    "status_code",
    "amount_cents",
    "currency",
    "idempotency_key",
    "failure_code",
    "attempt",
)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private keys, in whole or in part.
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----", re.S), "[PRIVATE KEY REDACTED]"),
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----"), "[PRIVATE KEY REDACTED]"),
    # JWTs — covers Poynt access tokens, payment tokens and our own assertions.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"), "[JWT REDACTED]"),
    # Anything that looks like a bare card number (13–19 digits, optional
    # separators), which must never appear in this application's logs at all.
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD REDACTED]"),
    # Explicit key/value forms for the obvious offenders.
    (re.compile(r"(?i)\b(cvv|cvc|cvv2|csc|pin)\b\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(authorization|access[_-]?token|private[_-]?key|assertion)\b\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactSensitiveFilter(logging.Filter):
    """Scrub secrets from a record's message and arguments before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        key: redact(value) if isinstance(value, str) else value
                        for key, value in record.args.items()
                    }
                else:
                    record.args = tuple(
                        redact(value) if isinstance(value, str) else value
                        for value in record.args
                    )
            for field in CONTEXT_FIELDS:
                value = getattr(record, field, None)
                if isinstance(value, str):
                    setattr(record, field, redact(value))
        except Exception:
            # Logging must never break the request that produced it.
            pass
        return True


class PaymentContextFormatter(logging.Formatter):
    """Append the structured payment fields present on the record."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        parts = []
        for field in CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                parts.append(f"{field}={value}")
        return f"{base} | {' '.join(parts)}" if parts else base
