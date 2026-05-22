Security-audit event catalog:
- admin_action: mirrored from Django admin LogEntry
- csv_upload: created by CSV validators/import flows
- payment_event: created by payment service adapters
- label_created: created by shipping service adapters
- order_status_change: created by order status signal
- role_change: created by account role change signal
- security_event: generic security telemetry events

Usage:
- import log_audit_event from security_audit.utils and pass action/message/actor/request/metadata.
