# OWASP Security Foundation

This project foundation is designed around OWASP Top 10 controls.

## Core implementation choices
- Access control is role-based with explicit view mixins/decorators.
- Secrets and hosts are environment-driven.
- Production settings enforce HTTPS and secure cookies.
- Services isolate payment/tax/shipping/fulfillment integrations.
- Payment flows use tokenized provider references only; no card PAN storage.
- CSV and file uploads are validated and audited.
- Security events are written to security_audit.AuditLog.
- Remote image URLs require https and optional host allowlist.
- Dependencies are pinned and Dependabot is configured.

## Secure coding rules
- Use Django ORM and parameterized APIs.
- Do not compose raw SQL from user input.
- Validate all user-controlled form/file input.
- Use the audit log for privileged and data-changing events.
