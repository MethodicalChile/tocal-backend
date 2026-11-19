"""Catálogo y administración de obras RBAC (T2.3). No sustituye los endpoints legados de intranet."""
import json
from datetime import date
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from intranet.models import Obra, Trabajador, Venta
from .models import Empresa, EmpresaObra, MembresiaEmpresa, RegistroAuditoria
from .permissions import authorized_obra_ids, has_permission


def _allowed(request, empresa_id, permission, obra_id=None):
    return (
        request.user.is_authenticated
        and request.user.is_active
        and Empresa.objects.filter(pk=empresa_id, activa=True).exists()
        and has_permission(user=request.user, permission=permission, empresa_id=empresa_id, obra_id=obra_id)
    )


def _record(v):
    obra = v.obra
    return {
        'id': v.obra_id,
        'nombre': obra.nombre,
        'servicio': obra.servicio,
        'activa': obra.activa,
        'razon_social': obra.razon_social,
        'rut': obra.rut,
        'direccion': obra.direccion or '',
        'mandante': obra.mandante or '',
        'adm_contrato': obra.adm_contrato or '',
        'asesor_pdr': obra.asesor_pdr or '',
        'asesor_mutual': obra.asesor_mutual or '',
        'monto_contractual_uf': obra.monto_contractual_uf,
        'anticipo_uf': obra.anticipo_uf,
        'inicio_contrato': obra.inicio_contrato.isoformat() if obra.inicio_contrato else None,
        'termino_contrato': obra.termino_contrato.isoformat() if obra.termino_contrato else None,
    }


def _build_obras_catalogos(empresa_id):
    """Construye opciones sugeridas de mandantes (con razón social y RUT), servicios, responsables y mutualidades."""
    mandantes_map = {}

    # 1. Mandantes / razones sociales desde Obras existentes
    for ob in Obra.objects.all().order_by('nombre'):
        label = (ob.mandante or ob.razon_social or '').strip()
        if label and label.lower() not in mandantes_map:
            mandantes_map[label.lower()] = {
                'mandante': label,
                'razon_social': (ob.razon_social or label).strip(),
                'rut': (ob.rut or '').strip(),
            }

    # 2. Clientes históricos desde Libro de Ventas (tocal_ventas_documentos)
    try:
        ventas_clientes = (
            Venta.objects.exclude(razon_social__isnull=True)
            .exclude(razon_social='')
            .values('razon_social', 'rut_cliente')
            .distinct()[:150]
        )
        for vc in ventas_clientes:
            rz = (vc.get('razon_social') or '').strip()
            rut_c = (vc.get('rut_cliente') or '').strip()
            if rz and rz.lower() not in mandantes_map:
                mandantes_map[rz.lower()] = {
                    'mandante': rz,
                    'razon_social': rz,
                    'rut': rut_c,
                }
    except Exception:
        pass

    # 3. Empresas registradas en la plataforma
    for emp in Empresa.objects.filter(activa=True).order_by('nombre'):
        if emp.nombre.lower() not in mandantes_map:
            mandantes_map[emp.nombre.lower()] = {
                'mandante': emp.nombre,
                'razon_social': emp.nombre,
                'rut': emp.rut or '',
            }

    # 4. Servicios habituales de constructora + existentes en obras
    servicios_base = [
        'Construcción y Obras Civiles',
        'Edificación Industrial y Galpones',
        'Montaje Estructural y Metálico',
        'Urbanización, Movimiento de Tierras y Pavimentación',
        'Habilitación Comercial e Institucional',
        'Obras Hidráulicas y Sanitarias',
        'Infraestructura Energética',
        'Remodelación y Mantención Mayor',
    ]
    for s in Obra.objects.values_list('servicio', flat=True).distinct():
        if s and s.strip() and s.strip() not in servicios_base:
            servicios_base.append(s.strip())

    # 5. Responsables (Trabajadores y Miembros de la empresa)
    responsables = []
    seen_resp = set()
    for w in Trabajador.objects.filter(empresa_id=empresa_id, activo=True).order_by('nombres', 'apellido_paterno'):
        full = f"{w.nombres} {w.apellido_paterno} {w.apellido_materno}".strip()
        if full and full.lower() not in seen_resp:
            seen_resp.add(full.lower())
            responsables.append(full)
    for m in MembresiaEmpresa.objects.filter(empresa_id=empresa_id, activa=True).select_related('usuario'):
        uname = (getattr(m.usuario, 'name', '') or m.usuario.email or '').strip()
        if uname and uname.lower() not in seen_resp:
            seen_resp.add(uname.lower())
            responsables.append(uname)

    mutualidades = [
        'ACHS (Asociación Chilena de Seguridad)',
        'Mutual de Seguridad CChC',
        'IST (Instituto de Seguridad del Trabajo)',
        'ISL (Instituto de Seguridad Laboral)',
    ]

    return {
        'mandantes': sorted(mandantes_map.values(), key=lambda x: x['mandante'].lower()),
        'servicios': servicios_base,
        'responsables': responsables,
        'mutualidades': mutualidades,
    }


@require_http_methods(['GET', 'POST'])
def company_works(request, empresa_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({'error': 'Autenticación requerida'}, status=401)
    if request.method == 'GET':
        if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        scope = authorized_obra_ids(user=request.user, permission='obras.ver', empresa_id=empresa_id)
        if scope == set():
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        entries = EmpresaObra.objects.filter(empresa_id=empresa_id).select_related('obra').order_by('obra__nombre')
        if scope is not None:
            entries = entries.filter(obra_id__in=scope)
        return JsonResponse({
            'results': [_record(entry) for entry in entries],
            'catalogos': _build_obras_catalogos(empresa_id),
        })

    if not _allowed(request, empresa_id, 'obras.crear'):
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    if len(request.body) > 16000:
        return JsonResponse({'error': 'Solicitud demasiado grande'}, status=400)
    try:
        data = json.loads(request.body)
        allowed = {
            'id',
            'nombre',
            'razon_social',
            'rut',
            'servicio',
            'direccion',
            'mandante',
            'adm_contrato',
            'asesor_pdr',
            'asesor_mutual',
            'inicio_contrato',
            'termino_contrato',
            'monto_contractual_uf',
            'anticipo_uf',
            'activa',
        }
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('Campos no admitidos')
        for key in ['id', 'nombre', 'razon_social', 'rut', 'servicio', 'inicio_contrato']:
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f'Campo obligatorio: {key}')
        date.fromisoformat(data['inicio_contrato'])
        if data.get('termino_contrato'):
            date.fromisoformat(data['termino_contrato'])
        obra = Obra(**{k: data[k] for k in allowed if k in data and data[k] is not None})
        obra.full_clean()
        with transaction.atomic():
            obra.save(force_insert=True)
            entry = EmpresaObra.objects.create(empresa_id=empresa_id, obra=obra)
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='obra.crear',
                entidad='Obra',
                entidad_id=str(obra.pk),
                detalle={'nombre': obra.nombre},
            )
        return JsonResponse(_record(entry), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except IntegrityError:
        return JsonResponse({'error': 'ID de obra duplicado o conflicto de integridad'}, status=409)


@require_http_methods(['GET', 'PATCH'])
def company_work_detail(request, empresa_id, obra_id):
    """Consulta, edición y activación/desactivación de una obra vinculada a la empresa (T2.3)."""
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({'error': 'Autenticación requerida'}, status=401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    entry = EmpresaObra.objects.select_related('obra').filter(empresa_id=empresa_id, obra_id=obra_id).first()
    if entry is None:
        return JsonResponse({'error': 'Obra no encontrada en la empresa'}, status=404)

    if request.method == 'GET':
        if not _allowed(request, empresa_id, 'obras.ver', obra_id=obra_id):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        return JsonResponse(_record(entry))

    if not _allowed(request, empresa_id, 'obras.editar', obra_id=obra_id):
        return JsonResponse({'error': 'Sin acceso'}, status=403)
    if len(request.body) > 16000:
        return JsonResponse({'error': 'Solicitud demasiado grande'}, status=400)
    try:
        data = json.loads(request.body)
        editable = {
            'nombre',
            'razon_social',
            'rut',
            'servicio',
            'direccion',
            'mandante',
            'adm_contrato',
            'asesor_pdr',
            'asesor_mutual',
            'inicio_contrato',
            'termino_contrato',
            'monto_contractual_uf',
            'anticipo_uf',
            'activa',
        }
        if not isinstance(data, dict) or not data or (set(data) - editable):
            raise ValueError('Campos no admitidos o vacíos')
        obra = entry.obra
        for key in ('nombre', 'razon_social', 'rut', 'servicio'):
            if key in data:
                if not isinstance(data[key], str) or not data[key].strip():
                    raise ValueError(f'El campo {key} no puede estar vacío')
                setattr(obra, key, data[key].strip())
        for key in ('direccion', 'mandante', 'adm_contrato', 'asesor_pdr', 'asesor_mutual'):
            if key in data:
                setattr(obra, key, data[key].strip() if isinstance(data[key], str) else '')
        if 'inicio_contrato' in data:
            obra.inicio_contrato = date.fromisoformat(data['inicio_contrato'])
        if 'termino_contrato' in data:
            obra.termino_contrato = date.fromisoformat(data['termino_contrato']) if data['termino_contrato'] else None
        for key in ('monto_contractual_uf', 'anticipo_uf'):
            if key in data and data[key] is not None:
                setattr(obra, key, float(data[key]))
        if 'activa' in data:
            if not isinstance(data['activa'], bool):
                raise ValueError('activa debe ser booleano')
            obra.activa = data['activa']
        obra.full_clean()
        with transaction.atomic():
            obra.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='obra.editar',
                entidad='Obra',
                entidad_id=str(obra.pk),
                detalle={'campos': sorted(data.keys()), 'activa': obra.activa},
            )
        return JsonResponse(_record(entry))
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
