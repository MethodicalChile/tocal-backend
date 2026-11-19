"""Canal autenticado para solicitudes de derechos ARCO+ (Ley 19.628 / Ley 21.719)."""
import json
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.authorization.models import AsignacionRol, RegistroAuditoria
from .models import SolicitudPrivacidad


def _can_manage_privacy(user):
    if not user.is_authenticated or not user.is_active:
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "rol", "") == "gerencia":
        return True
    return AsignacionRol.objects.filter(
        membresia__usuario=user,
        membresia__activa=True,
        activa=True,
        rol__activo=True,
        rol__permisos_asignados__permiso__codigo__in=["roles.administrar", "auditoria.ver"],
        rol__permisos_asignados__permiso__activo=True,
    ).exists()


@login_required
@require_http_methods(["GET", "POST"])
def requests(request):
    if request.method == "GET":
        rows = list(
            SolicitudPrivacidad.objects.filter(usuario=request.user).values(
                "id", "tipo", "detalle", "estado", "created_at", "closed_at"
            )[:100]
        )
        can_admin = _can_manage_privacy(request.user)
        admin_rows = []
        if can_admin:
            for s in SolicitudPrivacidad.objects.select_related("usuario").all()[:150]:
                admin_rows.append({
                    "id": s.id,
                    "usuario_id": s.usuario_id,
                    "usuario_nombre": getattr(s.usuario, "name", "") or s.usuario.username,
                    "usuario_email": getattr(s.usuario, "email", "") or s.usuario.username,
                    "tipo": s.tipo,
                    "detalle": s.detalle,
                    "estado": s.estado,
                    "created_at": s.created_at,
                    "closed_at": s.closed_at,
                })
        return JsonResponse({
            "results": rows,
            "can_manage": can_admin,
            "admin_results": admin_rows,
        })
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


@login_required
@require_http_methods(["PATCH"])
def manage_request(request, pk):
    if not _can_manage_privacy(request.user):
        return JsonResponse({"error": "Sin permiso para administrar solicitudes ARCO+."}, status=403)
    try:
        payload = json.loads(request.body or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido"}, status=400)
    nuevo_estado = payload.get("estado")
    if nuevo_estado not in dict(SolicitudPrivacidad.ESTADOS):
        return JsonResponse({"error": "Estado no válido."}, status=400)
    sol = get_object_or_404(SolicitudPrivacidad, pk=pk)
    sol.estado = nuevo_estado
    sol.closed_at = timezone.now() if nuevo_estado in ("resuelta", "rechazada") else None
    sol.save(update_fields=["estado", "closed_at"])
    return JsonResponse({
        "id": sol.id,
        "estado": sol.estado,
        "closed_at": sol.closed_at,
    })


@login_required
@require_http_methods(["GET"])
def portabilidad(request):
    """Ley N° 21.719: Derecho de Portabilidad de Datos Personales en formato electrónico estructurado."""
    from .models import Trabajador, AsignacionTrabajadorObra
    from apps.documents.models import DocumentoTrabajador, CapacitacionTrabajador, EntregaEPP

    u = request.user
    fichas = []
    for t in Trabajador.objects.filter(usuario=u).select_related("empresa"):
        asigs = [
            {
                "obra_id": a.obra_id,
                "obra_nombre": a.obra.nombre,
                "cargo": a.cargo.nombre,
                "fecha_inicio": a.fecha_inicio.isoformat() if a.fecha_inicio else None,
                "fecha_fin": a.fecha_fin.isoformat() if a.fecha_fin else None,
            }
            for a in AsignacionTrabajadorObra.objects.filter(trabajador=t).select_related("obra", "cargo")
        ]
        docs = [
            {
                "tipo_documento": d.tipo_documento.nombre,
                "estado": d.estado,
                "fecha_emision": d.fecha_emision.isoformat() if d.fecha_emision else None,
                "fecha_vencimiento": d.fecha_vencimiento.isoformat() if d.fecha_vencimiento else None,
            }
            for d in DocumentoTrabajador.objects.filter(trabajador=t).select_related("tipo_documento")
        ]
        caps = [
            {
                "curso_o_pts": c.tipo_capacitacion.nombre,
                "fecha_realizacion": c.fecha_realizacion.isoformat() if c.fecha_realizacion else None,
                "fecha_vencimiento": c.fecha_vencimiento.isoformat() if c.fecha_vencimiento else None,
                "estado": c.estado,
                "relator": c.relator,
            }
            for c in CapacitacionTrabajador.objects.filter(trabajador=t).select_related("tipo_capacitacion")
        ]
        epps = [
            {
                "elemento": e.elemento,
                "cantidad": e.cantidad,
                "fecha_entrega": e.fecha_entrega.isoformat() if e.fecha_entrega else None,
                "firmado_recepcion": e.firmado_recepcion,
            }
            for e in EntregaEPP.objects.filter(trabajador=t)
        ]
        fichas.append({
            "trabajador_id": t.pk,
            "empresa": t.empresa.nombre,
            "nombres": t.nombres,
            "apellido_paterno": t.apellido_paterno,
            "apellido_materno": t.apellido_materno,
            "rut": t.rut,
            "activo": t.activo,
            "asignaciones_obra": asigs,
            "documentos_laborales": docs,
            "capacitaciones_y_pts": caps,
            "entregas_epp": epps,
        })

    solicitudes = list(
        SolicitudPrivacidad.objects.filter(usuario=u).values(
            "id", "tipo", "detalle", "estado", "created_at", "closed_at"
        )[:100]
    )

    return JsonResponse({
        "normativa": "Ley N° 19.628 y Ley N° 21.719 sobre Protección y Portabilidad de Datos Personales (Chile)",
        "generado_en": timezone.now().isoformat(),
        "titular": {
            "id": u.pk,
            "username": u.username,
            "nombre": getattr(u, "name", "") or u.username,
            "email": getattr(u, "email", "") or u.username,
            "rol_base": getattr(u, "rol", ""),
            "ultimo_acceso": u.last_login.isoformat() if u.last_login else None,
        },
        "fichas_laborales_y_prevencion": fichas,
        "historial_solicitudes_arco": solicitudes,
    })

