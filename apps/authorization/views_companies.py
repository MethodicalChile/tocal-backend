"""Empresas visibles para el usuario autenticado y administración empresarial (T2.1)."""
import json
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods
from .models import AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa, Permiso, RegistroAuditoria, Rol, RolPermiso
from .permissions import has_any_obra_permission, has_permission
from .services import assign_role


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
    payload = {
        'id': str(empresa.pk),
        'nombre': empresa.nombre,
        'rut': empresa.rut,
        'activa': empresa.activa,
        'creado_en': empresa.creado_en.isoformat(),
        'total_obras': EmpresaObra.objects.filter(empresa=empresa).count(),
        'total_miembros_activos': MembresiaEmpresa.objects.filter(empresa=empresa, activa=True).count(),
    }
    return {**payload, 'empresa': payload}


@require_http_methods(['POST'])
def company_create(request):
    """Permite a un administrador crear una nueva empresa, aprovisionando roles base y membresía."""
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({'error': 'Autenticación requerida'}, status=401)

    # Verificar que el usuario sea superuser/staff o tenga permiso roles.administrar / empresas.editar en alguna empresa
    is_admin_anywhere = (
        request.user.is_superuser
        or request.user.is_staff
        or getattr(request.user, 'rol', '') in ('admin', 'gerencia')
        or AsignacionRol.objects.filter(
            membresia__usuario=request.user,
            membresia__activa=True,
            activa=True,
            rol__activo=True,
            rol__permisos_asignados__permiso__codigo__in=('roles.administrar', 'empresas.editar'),
        ).exists()
    )
    if not is_admin_anywhere:
        return JsonResponse({'error': 'No tienes permisos para crear nuevas empresas'}, status=403)

    try:
        if len(request.body) > 16_384:
            raise ValueError('Solicitud demasiado grande')
        data = json.loads(request.body.decode('utf-8'))
        if not isinstance(data, dict) or (set(data.keys()) - {'nombre', 'rut', 'sembrar_catalogos'}):
            raise ValueError('Campos inválidos')
        nombre = (data.get('nombre') or '').strip()
        if not nombre:
            raise ValueError('El nombre o razón social de la empresa es obligatorio')
        rut_val = (data.get('rut') or '').strip() or None
        if rut_val and Empresa.objects.filter(rut=rut_val).exists():
            return JsonResponse({'error': 'Ya existe una empresa registrada con ese RUT'}, status=409)
        sembrar = bool(data.get('sembrar_catalogos', True))

        with transaction.atomic():
            nueva = Empresa(nombre=nombre[:200], rut=rut_val, activa=True)
            nueva.full_clean()
            nueva.save()

            # Crear membresía activa para el creador
            membresia = MembresiaEmpresa.objects.create(
                empresa=nueva,
                usuario=request.user,
                activa=True,
            )

            # Crear rol Administrador General con todos los permisos activos y asignarlo al creador
            rol_admin = Rol.objects.create(
                empresa=nueva,
                codigo='administrador_general',
                nombre='Administrador General',
                descripcion='Acceso administrativo y operacional completo en la empresa.',
                activo=True,
                protegido=True,
            )
            permisos_activos = list(Permiso.objects.filter(activo=True))
            RolPermiso.objects.bulk_create([
                RolPermiso(rol=rol_admin, permiso=p) for p in permisos_activos
            ])
            assign_role(usuario=request.user, empresa=nueva, rol=rol_admin, obra=None)

            # Crear roles operativos estándar para la nueva empresa
            roles_operativos = [
                ('prevencionista', 'Prevencionista de Riesgos', 'Gestión documental, capacitaciones, EPP, checklists y cumplimiento DS 44.'),
                ('jefe_obra', 'Jefe / Administrador de Obra', 'Supervisión integral de obra, avance físico, personal y cumplimiento.'),
                ('supervisor', 'Supervisor / Jefe de Terreno', 'Consulta rápida en terreno, checklists e informes operacionales.'),
                ('trabajador', 'Trabajador / Lectura', 'Consulta de información autorizada.'),
            ]
            for cod, nom, desc in roles_operativos:
                Rol.objects.get_or_create(
                    empresa=nueva,
                    codigo=cod,
                    defaults={'nombre': nom, 'descripcion': desc, 'activo': True, 'protegido': False},
                )

            if sembrar:
                from apps.documents.seed_tocal import sembrar_catalogos_base_tocal
                sembrar_catalogos_base_tocal(nueva.pk, actor=request.user)

            RegistroAuditoria.objects.create(
                empresa=nueva,
                actor=request.user,
                accion='empresa.crear',
                entidad='Empresa',
                entidad_id=str(nueva.pk),
                detalle={'nombre': nueva.nombre, 'rut': nueva.rut, 'sembrar_catalogos': sembrar},
            )

        return JsonResponse(_serialize_empresa(nueva), status=201)
    except (ValueError, TypeError, ValidationError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({'error': 'Ya existe una empresa con ese nombre o RUT'}, status=409)


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
