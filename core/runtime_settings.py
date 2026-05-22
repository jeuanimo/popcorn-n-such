from __future__ import annotations

import os

from django.conf import settings
from django.core.cache import cache


def get_runtime_setting(attr_name: str, fallback=None):
    """
    Priority order:
    1. Environment variable (highest — deployment overrides)
    2. OperationalSettings row in the database (staff-editable via GUI)
    3. Django settings attribute
    4. fallback argument
    """
    env_key = attr_name.upper()

    value = os.getenv(env_key, None)
    if value not in (None, ""):
        return value

    db_value = _get_from_db(attr_name)
    if db_value not in (None, ""):
        return db_value

    django_value = getattr(settings, env_key, None)
    if django_value not in (None, ""):
        return django_value

    return fallback


_CACHE_KEY = "runtime_settings:operational_settings"
_CACHE_TTL = 60  # seconds — short enough to pick up GUI changes quickly


def _get_from_db(attr_name: str):
    row = cache.get(_CACHE_KEY)
    if row is None:
        row = _load_db_row()
        cache.set(_CACHE_KEY, row, timeout=_CACHE_TTL)
    return row.get(attr_name)


def _load_db_row() -> dict:
    try:
        from core.models import OperationalSettings
        obj = OperationalSettings.objects.order_by("pk").last()
        if obj is None:
            return {}
        return {
            field.name: getattr(obj, field.name)
            for field in obj._meta.fields
            if isinstance(getattr(obj, field.name), str)
        }
    except Exception:
        return {}
