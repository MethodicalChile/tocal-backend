"""Catálogo de obras RBAC. No sustituye los endpoints legados de intranet."""
import json
from datetime import date
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from intranet.models import Obra
from .models import Empresa, EmpresaObra, RegistroAuditoria
from .permissions import has_permission


def _allowed(request, empresa_id, permission):
    return (request.user.is_authenticated and request.user.is_active and
            Empresa.objects.filter(pk=empresa_id, activa=True).exists() and
            has_permission(user=request.user, permission=permission, empresa_id=empresa_id))


def _record(v):
    return {'id': v.obra_id, 'nombre': v.obra.nombre, 'servicio': v.obra.servicio,
            'activa': v.obra.activa, 'razon_social': v.obra.razon_social,
            'inicio_contrato': v.obra.inicio_contrato.isoformat()}


@require_http_methods(['GET', 'POST'])
def company_works(request, empresa_id):
    if request.method == 'GET':
        if not _allowed(request, empresa_id, 'obras.ver'):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        entries = EmpresaObra.objects.filter(empresa_id=empresa_id).select_related('obra').order_by('obra__nombre')
        return JsonResponse({'results': [_record(entry) for entry in entries]})

    if not _allowed(request, empresa_id, 'obras.crear'):
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    if len(request.body) > 16000:
        return JsonResponse({'error': 'Solicitud demasiado grande'}, status=400)
    try:
        data = json.loads(request.body)
        allowed = {'id', 'nombre', 'razon_social', 'rut', 'servicio', 'inicio_contrato', 'monto_contractual_uf', 'anticipo_uf'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('Campos no admitidos')
        for key in ['id', 'nombre', 'razon_social', 'rut', 'servicio', 'inicio_contrato']:
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f'Campo obligatorio: {key}')
        date.fromisoformat(data['inicio_contrato'])
        obra = Obra(**{k: data[k] for k in allowed if k in data})
        obra.full_clean()
        with transaction.atomic():
            obra.save(force_insert=True)
            entry = EmpresaObra.objects.create(empresa_id=empresa_id, obra=obra)
            RegistroAuditoria.objects.create(empresa_id=empresa_id, actor=request.user,
                accion='obra.crear', entidad='Obra', entidad_id=str(obra.pk), detalle={'nombre': obra.nombre})
        return JsonResponse(_record(entry), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except Exception as exc:
        # Avoid exposing DB internals and duplicate identifiers.
        from django.db import IntegrityError
        if isinstance(exc, IntegrityError):
            return JsonResponse({'error': 'ID de obra duplicado o conflicto de integridad'}, status=409)
        raise
