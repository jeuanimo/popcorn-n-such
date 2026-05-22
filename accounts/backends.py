from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache


class ThrottledModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username:
            failures = cache.get(f"auth:failed:{username}", 0)
            if failures >= settings.LOGIN_THROTTLE_LIMIT:
                return None
        return super().authenticate(request, username=username, password=password, **kwargs)
