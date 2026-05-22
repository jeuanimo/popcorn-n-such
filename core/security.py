from __future__ import annotations

from functools import wraps
from typing import Iterable

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


ROLE_ALIAS_MAP = {
    "admin_owner": "admin",
    "fundraiser_seller": "seller",
    "registered_customer": "customer",
    "public_customer": "customer",
}


def normalize_role(role_name: str) -> str:
    return ROLE_ALIAS_MAP.get(role_name, role_name)


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not self.allowed_roles:
            return super().dispatch(request, *args, **kwargs)
        normalized = {normalize_role(role) for role in self.allowed_roles}
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if hasattr(request.user, "has_any_role") and request.user.has_any_role(*normalized):
            return super().dispatch(request, *args, **kwargs)
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if request.user.is_staff and "staff" in normalized:
            return super().dispatch(request, *args, **kwargs)
        if getattr(request.user, "role", None) not in normalized:
            raise PermissionDenied("You do not have permission for this page.")
        return super().dispatch(request, *args, **kwargs)


class OwnerFilteredQuerysetMixin(LoginRequiredMixin):
    owner_field = "user"
    staff_bypass = True

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.staff_bypass and (self.request.user.is_staff or self.request.user.is_superuser):
            return queryset
        return queryset.filter(**{self.owner_field: self.request.user})


class TeamCaptainQuerysetMixin(OwnerFilteredQuerysetMixin):
    owner_field = "captain"


class OrganizationManagerQuerysetMixin(OwnerFilteredQuerysetMixin):
    owner_field = "manager"


def role_required(roles: Iterable[str]):
    allowed = {normalize_role(role) for role in roles}

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if hasattr(request.user, "has_any_role") and request.user.has_any_role(*allowed):
                return view_func(request, *args, **kwargs)
            if request.user.is_superuser or getattr(request.user, "role", None) in allowed:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("Insufficient role permission.")

        return _wrapped

    return decorator
