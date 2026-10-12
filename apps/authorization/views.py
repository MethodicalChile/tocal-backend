"""API administrativa inicial: operaciones acotadas, sin asignación de roles.

Las rutas son de sesión Django: SessionAuthentication implícita y CSRF middleware.
No utilizar csrf_exempt. Solo se permite administración con rol de empresa.
"""
import json
import logging
import uuid
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Empresa, Permiso, Rol, RolPermiso, RegistroAuditoria
from .permissions import effective_permissions, has_permission

logger = logging.getLogger(__name__)


def endpoint(methods):
    def wrapper(fn):
        @wraps(fn)
        @require_http_methods(methods)
        def view(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.is_active:
                return JsonResponse({'error': 'Autenticación requerida'}, status=401)
            try:
                return fn(request, *args, **kwargs)
            except (ValueError, TypeError, ValidationError) as exc:
                return JsonResponse({'error': str(exc)}, status=400)
            except IntegrityError:
                logger.warning('Conflicto de integridad en autorización', exc_info=True)
                return JsonResponse({'error': 'Registro duplicado o incompatible'}, status=409)
        return view
    return wrapper


def _empresa(request, empresa_id, permiso='roles.ver'):
    empresa = Empresa.objects.filter(pk=empresa_id, activa=True).first()
    if empresa is None:
        return None
    if not has_permission(user=request.user, permission=permiso, empresa_id=empresa.pk):
        return None
    return empresa


def _json_body(request):
    if len(request.body) > 64_000:
        raise ValueError('Solicitud demasiado grande')
    data = json.loads(request.body.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Se esperaba un objeto JSON')
    return data


def _role_dict(role):
    return {'id': str(role.pk), 'codigo': role.codigo, 'nombre': role.nombre,
            'descripcion': role.descripcion, 'activo': role.activo,
            'protegido': role.protegido,
            'permisos': list(role.permisos_asignados.order_by('permiso__codigo').values_list('permiso__codigo', flat=True))}


@endpoint(['GET'])
def roles_list(request, empresa_id):
    empresa = _empresa(request, empresa_id)
    if empresa is None:
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    return JsonResponse({'results': [_role_dict(rol) for rol in Rol.objects.filter(empresa=empresa).prefetch_related('permisos_asignados')]})


@endpoint(['GET'])
def permissions_list(request, empresa_id):
    empresa = _empresa(request, empresa_id)
    if empresa is None:
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    return JsonResponse({'results': list(Permiso.objects.filter(activo=True).values('codigo', 'modulo', 'accion', 'nombre'))})


@endpoint(['GET'])
def my_permissions(request, empresa_id):
    # Esta ruta la puede usar cualquier miembro activo sin permiso administrativo.
    permissions = sorted(effective_permissions(user=request.user, empresa_id=empresa_id))
    if not permissions:
        return JsonResponse({'permissions': []})
    return JsonResponse({'permissions': permissions})


@endpoint(['POST'])
def roles_create(request, empresa_id):
    empresa = _empresa(request, empresa_id, 'roles.administrar')
    if empresa is None:
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    data = _json_body(request)
    if not isinstance(data.get('codigo'), str) or not isinstance(data.get('nombre'), str):
        raise ValueError('codigo y nombre son obligatorios')
    if data.keys() - {'codigo', 'nombre', 'descripcion'}:
        raise ValueError('Campos no admitidos')
    role = Rol(empresa=empresa, codigo=data['codigo'], nombre=data['nombre'], descripcion=data.get('descripcion', ''))
    role.full_clean()
    with transaction.atomic():
        role.save()
        RegistroAuditoria.objects.create(empresa=empresa, actor=request.user, accion='rol.crear', entidad='Rol', entidad_id=str(role.pk), detalle={'codigo': role.codigo})
    return JsonResponse(_role_dict(role), status=201)


@endpoint(['PUT'])
def role_permissions_replace(request, empresa_id, rol_id):
    empresa = _empresa(request, empresa_id, 'roles.administrar')
    if empresa is None:
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    data = _json_body(request)
    requested = data.get('permisos')
    if set(data) != {'permisos'} or not isinstance(requested, list) or any(not isinstance(code, str) for code in requested):
        raise ValueError('Se requiere lista de permisos')
    if len(requested) != len(set(requested)) or len(requested) > 200:
        raise ValueError('Permisos duplicados o lista demasiado grande')
    requested_set = set(requested)
    # Previene otorgar una capacidad mayor que la del administrador que ejecuta la operación.
    actor_permissions = effective_permissions(user=request.user, empresa_id=empresa.pk)
    if not requested_set.issubset(actor_permissions):
        return JsonResponse({'error': 'No puedes otorgar permisos que no posees'}, status=403)
    with transaction.atomic():
        role = Rol.objects.select_for_update().filter(pk=rol_id, empresa=empresa).first()
        if role is None:
            return JsonResponse({'error': 'Rol no encontrado'}, status=404)
        if role.protegido or role.asignaciones.filter(activa=True).exists():
            return JsonResponse({'error': 'No se puede cambiar un rol protegido o asignado; requiere flujo controlado'}, status=409)
        perms = list(Permiso.objects.filter(codigo__in=requested_set, activo=True))
        if len(perms) != len(requested_set):
            raise ValueError('Hay permisos inexistentes o inactivos')
        current = set(role.permisos_asignados.values_list('permiso__codigo', flat=True))
        role.permisos_asignados.all().delete()
        RolPermiso.objects.bulk_create([RolPermiso(rol=role, permiso=permiso) for permiso in perms])
        RegistroAuditoria.objects.create(empresa=empresa, actor=request.user, accion='rol.permisos_actualizar', entidad='Rol', entidad_id=str(role.pk), detalle={'antes': sorted(current), 'despues': sorted(requested_set)})
    return JsonResponse(_role_dict(role))
