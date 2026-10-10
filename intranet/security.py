"""Protege las páginas privadas contra cacheos compartidos por error."""
from django.utils.cache import patch_vary_headers

class PrivateNoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated or request.path.startswith(("/login", "/api/")):
            response["Cache-Control"] = "private, no-store, max-age=0"
            patch_vary_headers(response, ["Cookie"])
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
