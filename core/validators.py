from __future__ import annotations

import csv
import io
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


def validate_upload_file(file_obj, *, allowed_extensions: tuple[str, ...], max_size_bytes: int = 5_000_000):
    name = (getattr(file_obj, "name", "") or "").lower()
    if not name.endswith(allowed_extensions):
        raise ValidationError("Unsupported file extension.")
    if getattr(file_obj, "size", 0) > max_size_bytes:
        raise ValidationError("Uploaded file exceeds size limit.")


def validate_csv_upload(file_obj, *, required_columns: list[str], actor=None, request=None):
    validate_upload_file(file_obj, allowed_extensions=(".csv",))

    payload = file_obj.read().decode("utf-8")
    file_obj.seek(0)
    reader = csv.DictReader(io.StringIO(payload))

    if not reader.fieldnames:
        raise ValidationError("CSV header is missing.")

    missing = [col for col in required_columns if col not in reader.fieldnames]
    if missing:
        raise ValidationError(f"Missing required CSV columns: {', '.join(missing)}")

    log_audit_event(
        action=AuditAction.CSV_UPLOAD,
        message="CSV file validated",
        actor=actor,
        request=request,
        metadata={"filename": getattr(file_obj, "name", ""), "columns": reader.fieldnames},
    )

    return reader


def validate_json_dict(value):
    if not isinstance(value, dict):
        raise ValidationError("Value must be a JSON object (dict).")


def validate_json_list(value):
    if not isinstance(value, list):
        raise ValidationError("Value must be a JSON array (list).")


def validate_remote_image_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError("Only https remote images are allowed.")

    if not parsed.hostname:
        raise ValidationError("Invalid remote image URL.")

    allowed_hosts = set(getattr(settings, "ALLOWED_REMOTE_IMAGE_HOSTS", []))
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise ValidationError("Remote image host is not allowed.")

    return url
