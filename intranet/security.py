"""Protege las páginas privadas contra cacheos compartidos por error y controla expiración por inactividad."""
import time
from django.conf import settings
from django.contrib.auth import logout
from django.utils.cache import patch_vary_headers


class PrivateNoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            timeout_seconds = int(getattr(settings, "SESSION_INACTIVITY_TIMEOUT_SECONDS", 300) or 300)
            now_ts = int(time.time())
            last_ts = request.session.get("_last_activity_ts")
            if last_ts is not None and timeout_seconds > 0 and (now_ts - int(last_ts)) > timeout_seconds:
                logout(request)
            else:
                request.session["_last_activity_ts"] = now_ts

        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith(("/login", "/api/")):
            response["Cache-Control"] = "private, no-store, max-age=0"
            patch_vary_headers(response, ["Cookie"])
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
