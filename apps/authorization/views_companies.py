"""Empresas visibles para el usuario autenticado y administración empresarial (T2.1)."""
import json
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods
from .models import AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa, RegistroAuditoria
from .permissions import has_any_obra_permission, has_permission


@require_GET
def my_companies(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({'error': 'Autenticación requerida'}, status=401)
    membresias = (
        MembresiaEmpresa.objects.filter(
            usuario=request.user,
            activa=True,
            empresa__activa=True,
        )
        .select_related('empresa')
        .order_by('empresa__nombre')
    )
    results = []
    for membership in membresias:
        grants = AsignacionRol.objects.filter(
            membresia=membership,
            activa=True,
            rol__activo=True,
            rol__empresa_id=F('membresia__empresa_id'),
            rol__permisos_asignados__permiso__activo=True,
        ).filter(
            Q(empresa_obra__isnull=True)
            | Q(empresa_obra__empresa_id=F('membresia__empresa_id'))
        )
        global_role = grants.filter(empresa_obra__isnull=True).exists()
        links = EmpresaObra.objects.filter(empresa=membership.empresa)
        if not global_role:
            links = links.filter(
                id__in=grants.exclude(empresa_obra__isnull=True).values('empresa_obra_id')
            )
        results.append({
            'id': str(membership.empresa_id),
            'nombre': membership.empresa.nombre,
            'rut': membership.empresa.rut,
            'activa': membership.empresa.activa,
            'obra_ids': list(links.values_list('obra_id', flat=True)),
        })
    return JsonResponse({'results': results})


def _serialize_empresa(empresa):
    return {
        'id': str(empresa.pk),
        'nombre': empresa.nombre,
        'rut': empresa.rut,
        'activa': empresa.activa,
        'creado_en': empresa.creado_en.isoformat(),
        'total_obras': EmpresaObra.objects.filter(empresa=empresa).count(),
        'total_miembros_activos': MembresiaEmpresa.objects.filter(empresa=empresa, activa=True).count(),
    }


@require_http_methods(['GET', 'PATCH'])
def company_detail(request, empresa_id):
    """Consulta y edición de datos generales de la empresa (T2.1)."""
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({'error': 'Autenticación requerida'}, status=401)
    empresa = Empresa.objects.filter(pk=empresa_id).first()
    if empresa is None:
        return JsonResponse({'error': 'Sin acceso'}, status=403)

    if request.method == 'GET':
        has_access = (
            has_any_obra_permission(user=request.user, permission='empresas.ver', empresa_id=empresa_id)
            or has_any_obra_permission(user=request.user, permission='roles.ver', empresa_id=empresa_id)
            or has_any_obra_permission(user=request.user, permission='obras.ver', empresa_id=empresa_id)
        )
        if not has_access or not empresa.activa:
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        return JsonResponse(_serialize_empresa(empresa))

    can_edit = (
        has_permission(user=request.user, permission='empresas.editar', empresa_id=empresa_id)
        or has_permission(user=request.user, permission='roles.administrar', empresa_id=empresa_id)
    )
    if not can_edit:
        return JsonResponse({'error': 'Sin acceso'}, status=403)

    try:
        if len(request.body) > 16_384:
            raise ValueError('Solicitud demasiado grande')
        data = json.loads(request.body.decode('utf-8'))
        if not isinstance(data, dict) or not data or (set(data.keys()) - {'nombre', 'rut', 'activa'}):
            raise ValueError('Campos inválidos o vacíos')
        if 'nombre' in data:
            if not isinstance(data['nombre'], str) or not data['nombre'].strip():
                raise ValueError('El nombre de la empresa es obligatorio')
            empresa.nombre = data['nombre'].strip()
        if 'rut' in data:
            rut_val = data['rut'].strip() if isinstance(data.get('rut'), str) else None
            if rut_val and Empresa.objects.filter(rut=rut_val).exclude(pk=empresa.pk).exists():
                return JsonResponse({'error': 'Ya existe otra empresa con ese RUT'}, status=409)
            empresa.rut = rut_val or None
        if 'activa' in data:
            if not isinstance(data['activa'], bool):
                raise ValueError('El campo activa debe ser booleano')
            empresa.activa = data['activa']
        empresa.full_clean()
        with transaction.atomic():
            empresa.save()
            RegistroAuditoria.objects.create(
                empresa=empresa,
                actor=request.user,
                accion='empresa.editar',
                entidad='Empresa',
                entidad_id=str(empresa.pk),
                detalle={'campos': sorted(data.keys()), 'activa': empresa.activa},
            )
        return JsonResponse(_serialize_empresa(empresa))
    except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({'error': 'Conflicto de datos únicos en empresa'}, status=409)
