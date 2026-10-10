"""Canal autenticado para solicitudes de derechos, con evaluación humana posterior."""
import json
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import SolicitudPrivacidad


@login_required
@require_http_methods(["GET", "POST"])
def requests(request):
    if request.method == "GET":
        rows = SolicitudPrivacidad.objects.filter(usuario=request.user).values(
            "id", "tipo", "estado", "created_at", "closed_at"
        )[:100]
        return JsonResponse({"results": list(rows)})
    if request.content_type != "application/json" or len(request.body) > 3000:
        return JsonResponse({"error": "Solicitud JSON inválida"}, status=400)
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Solicitud inválida"}, status=400)
    kind, detail = payload.get("tipo"), payload.get("detalle", "")
    if kind not in dict(SolicitudPrivacidad.TIPO) or not isinstance(detail, str) or len(detail) > 1000:
        return JsonResponse({"error": "Tipo o detalle inválido"}, status=400)
    if SolicitudPrivacidad.objects.filter(
        usuario=request.user, created_at__gte=timezone.now() - timedelta(days=1)
    ).count() >= 5:
        return JsonResponse({"error": "Límite diario de solicitudes"}, status=429)
    obj = SolicitudPrivacidad.objects.create(usuario=request.user, tipo=kind, detalle=detail)
    return JsonResponse({"id": obj.id, "estado": obj.estado}, status=201)
