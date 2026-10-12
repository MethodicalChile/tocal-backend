"""Administración de membresías y asignaciones por empresa (API JSON Django).

Todas las operaciones de escritura están serializadas bloqueando Empresa.
No se debe usar csrf_exempt; SecurityMiddleware/CsrfViewMiddleware deben estar activos.
"""
from functools import wraps
import json
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import (AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa,
                     RegistroAuditoria, Rol)
from .permissions import effective_permissions, has_permission
from .services import assign_role


def route(methods):
    def decorator(fn):
        @wraps(fn)
        @require_http_methods(methods)
        def inner(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.is_active:
                return JsonResponse({'error': 'Autenticación requerida'}, status=401)
            try:
                return fn(request, *args, **kwargs)
            except (ValidationError, ValueError, TypeError) as exc:
                return JsonResponse({'error': str(exc)}, status=400)
            except IntegrityError:
                return JsonResponse({'error': 'Conflicto de integridad'}, status=409)
        return inner
    return decorator


def payload(request):
    if len(request.body) > 16_384:
        raise ValueError('Solicitud demasiado grande')
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('JSON inválido')
    if not isinstance(data, dict):
        raise ValueError('Se requiere un objeto JSON')
    return data


def parse_uuid(value, name):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f'{name} debe ser UUID')


def can_admin(user, empresa):
    # Solo administradores a nivel de empresa, no administradores de una obra.
    return has_permission(user=user, empresa_id=empresa.pk, permission='roles.administrar')


def audit(empresa, actor, action, obj, details):
    RegistroAuditoria.objects.create(
        empresa=empresa, actor=actor, accion=action,
        entidad=type(obj).__name__, entidad_id=str(obj.pk), detalle=details,
    )


def assignment_dict(a):
    return {'id': str(a.pk), 'usuario_id': a.membresia.usuario_id,
            'rol_id': str(a.rol_id), 'rol': a.rol.codigo,
            'obra_id': a.empresa_obra.obra_id if a.empresa_obra_id else None,
            'activa': a.activa}


def has_company_admin(empresa):
    """Debe existir un usuario activo con administración global vigente."""
    return AsignacionRol.objects.filter(
        membresia__empresa=empresa, membresia__activa=True,
        membresia__usuario__is_active=True, activa=True,
        empresa_obra__isnull=True, rol__empresa=empresa, rol__activo=True,
        rol__permisos_asignados__permiso__codigo='roles.administrar',
        rol__permisos_asignados__permiso__activo=True,
    ).exists()


@route(['GET'])
def members_list(request, empresa_id):
    empresa = Empresa.objects.filter(pk=empresa_id, activa=True).first()
    if not empresa or not (can_admin(request.user, empresa) or
                          has_permission(user=request.user, empresa_id=empresa_id,
                                         permission='usuarios.ver')):
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    qs = MembresiaEmpresa.objects.filter(empresa=empresa).select_related('usuario').order_by('usuario_id')
    return JsonResponse({'results': [
        {'id': str(m.pk), 'usuario_id': m.usuario_id,
         'username': m.usuario.get_username(), 'activa': m.activa}
        for m in qs
    ]})


@route(['POST'])
def member_add(request, empresa_id):
    data = payload(request)
    if set(data) != {'usuario_id'}:
        raise ValueError('Se requiere usuario_id')
    User = get_user_model()
    with transaction.atomic():
        empresa = Empresa.objects.select_for_update().filter(pk=empresa_id, activa=True).first()
        if not empresa or not can_admin(request.user, empresa):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        user = User.objects.filter(pk=data['usuario_id'], is_active=True).first()
        if user is None:
            return JsonResponse({'error': 'Usuario no encontrado o inactivo'}, status=404)
        member, created = MembresiaEmpresa.objects.get_or_create(empresa=empresa, usuario=user)
        if not member.activa:
            member.activa = True
            member.save(update_fields=['activa'])
        audit(empresa, request.user, 'membresia.habilitar', member,
              {'usuario_id': user.pk, 'creada': created})
    return JsonResponse({'id': str(member.pk), 'usuario_id': user.pk, 'activa': True}, status=201 if created else 200)


@route(['GET'])
def assignments_list(request, empresa_id):
    empresa = Empresa.objects.filter(pk=empresa_id, activa=True).first()
    if not empresa or not can_admin(request.user, empresa):
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    qs = (AsignacionRol.objects.filter(membresia__empresa=empresa)
          .select_related('membresia', 'rol', 'empresa_obra').order_by('creado_en'))
    return JsonResponse({'results': [assignment_dict(a) for a in qs]})


@route(['POST'])
def assignment_add(request, empresa_id):
    data = payload(request)
    if not {'usuario_id', 'rol_id'} <= set(data) or set(data) - {'usuario_id', 'rol_id', 'obra_id'}:
        raise ValueError('Se requieren usuario_id y rol_id; obra_id es opcional')
    role_id = parse_uuid(data['rol_id'], 'rol_id')
    with transaction.atomic():
        empresa = Empresa.objects.select_for_update().filter(pk=empresa_id, activa=True).first()
        if not empresa or not can_admin(request.user, empresa):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        membership = MembresiaEmpresa.objects.select_for_update().filter(
            empresa=empresa, usuario_id=data['usuario_id'], activa=True,
            usuario__is_active=True).select_related('usuario').first()
        if membership is None:
            return JsonResponse({'error': 'El usuario no tiene membresía activa'}, status=404)
        role = Rol.objects.filter(pk=role_id, empresa=empresa, activo=True).first()
        if role is None:
            return JsonResponse({'error': 'Rol no encontrado'}, status=404)
        obra = None
        if data.get('obra_id') is not None:
            vinculo = EmpresaObra.objects.filter(empresa=empresa, obra_id=data['obra_id']).select_related('obra').first()
            if vinculo is None:
                return JsonResponse({'error': 'Obra no pertenece a la empresa'}, status=400)
            obra = vinculo.obra
        actor_caps = effective_permissions(user=request.user, empresa_id=empresa.pk, obra_id=getattr(obra, 'pk', None))
        role_caps = set(role.permisos_asignados.filter(permiso__activo=True).values_list('permiso__codigo', flat=True))
        if not role_caps.issubset(actor_caps):
            return JsonResponse({'error': 'No puedes conceder permisos que no posees en ese ámbito'}, status=403)
        assignment = assign_role(usuario=membership.usuario, empresa=empresa, rol=role, obra=obra)
        audit(empresa, request.user, 'asignacion.habilitar', assignment,
              {'usuario_id': membership.usuario_id, 'rol_id': str(role.pk),
               'obra_id': getattr(obra, 'pk', None)})
    return JsonResponse(assignment_dict(assignment), status=200)


@route(['POST'])
def assignment_revoke(request, empresa_id, assignment_id):
    with transaction.atomic():
        empresa = Empresa.objects.select_for_update().filter(pk=empresa_id, activa=True).first()
        if not empresa or not can_admin(request.user, empresa):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        assignment = (
            AsignacionRol.objects
            .select_for_update(of=("self",))
            .select_related(
                "membresia",
                "rol",
                "empresa_obra",
            )
            .filter(
                pk=assignment_id,
                membresia__empresa_id=empresa_id,
            )
            .first()
        )
        if not assignment:
            return JsonResponse({'error': 'Asignación no encontrada'}, status=404)
        if not assignment.activa:
            return JsonResponse(assignment_dict(assignment))
        # Un administrador de empresa puede revocar roles en empresa u obra.
        assignment.activa = False
        assignment.save(update_fields=['activa'])
        if not has_company_admin(empresa):
            transaction.set_rollback(True)
            return JsonResponse({'error': 'No se puede revocar el último administrador de la empresa'}, status=409)
        audit(empresa, request.user, 'asignacion.revocar', assignment,
              {'usuario_id': assignment.membresia.usuario_id,
               'rol_id': str(assignment.rol_id)})
        return JsonResponse(assignment_dict(assignment))
