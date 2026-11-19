"""Endpoints JSON para catálogo y requisitos, sin contenido de archivos."""
import json
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from apps.authorization.models import Empresa, EmpresaObra, RegistroAuditoria
from apps.authorization.permissions import authorized_obra_ids, has_any_obra_permission, has_permission
from intranet.models import AsignacionTrabajadorObra, Cargo
from .models import TipoDocumento, RequisitoDocumental


def _response_error(message, code=400):
    return JsonResponse({'error': message}, status=code)


def _unauthenticated(request):
    return not request.user.is_authenticated or not request.user.is_active


def _authorized(request, empresa_id, permission, obra_id=None):
    return has_permission(user=request.user, empresa_id=empresa_id, obra_id=obra_id, permission=permission)


def _authorized_any_obra(request, empresa_id, permission, obra_ids=None):
    return has_any_obra_permission(
        user=request.user,
        empresa_id=empresa_id,
        permission=permission,
        obra_ids=obra_ids,
    )


def _worker_obra_ids(empresa_id, trabajador_id):
    return set(
        AsignacionTrabajadorObra.objects.filter(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id,
        ).values_list('obra_id', flat=True)
    )


def _authorized_for_worker(request, empresa_id, trabajador_id, permission):
    if _authorized(request, empresa_id, permission, obra_id=None):
        return True
    worker_obras = _worker_obra_ids(empresa_id, trabajador_id)
    if not worker_obras:
        return False
    return _authorized_any_obra(request, empresa_id, permission, obra_ids=worker_obras)


def _can_review_document(request, empresa_id, trabajador_id, obra_id=None):
    for perm in ('documentos.aprobar', 'documentos.editar'):
        if obra_id is not None:
            if _authorized(request, empresa_id, perm, obra_id=obra_id):
                return True
        else:
            if _authorized_for_worker(request, empresa_id, trabajador_id, perm):
                return True
    return False


def _can_download_document(request, empresa_id, trabajador_id, obra_id=None):
    for perm in ('documentos.descargar', 'documentos.ver'):
        if obra_id is not None:
            if _authorized(request, empresa_id, perm, obra_id=obra_id):
                return True
        else:
            if _authorized_for_worker(request, empresa_id, trabajador_id, perm):
                return True
    return False


def _payload(request):
    if len(request.body) > 16384:
        raise ValueError('Solicitud demasiado grande.')
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('JSON inválido.')
    if not isinstance(data, dict):
        raise ValueError('Se espera un objeto JSON.')
    return data


def _fields(data, allowed):
    if set(data) - allowed:
        raise ValueError('Campos no admitidos.')


def _boolean(data, key, default):
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f'{key} debe ser booleano.')
    return value


def _serialize_tipo(item):
    return {'id': str(item.pk), 'codigo': item.codigo, 'nombre': item.nombre,
            'categoria': item.categoria, 'descripcion': item.descripcion,
            'requiere_vencimiento': item.requiere_vencimiento, 'activo': item.activo}


def _serialize_requisito(item):
    return {'id': str(item.pk), 'tipo_documento_id': str(item.tipo_documento_id),
            'cargo_id': item.cargo_id, 'obra_id': item.obra_id,
            'obligatorio': item.obligatorio, 'activo': item.activo}


@require_http_methods(['GET', 'POST'])
def tipos(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        items = TipoDocumento.objects.filter(empresa_id=empresa_id).order_by('nombre')[:500]
        return JsonResponse({'results': [_serialize_tipo(i) for i in items]})
    if not _authorized(request, empresa_id, 'documentos.crear'):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'codigo', 'nombre', 'categoria', 'descripcion', 'requiere_vencimiento', 'activo'})
        if not all(isinstance(data.get(k), str) and data[k].strip() for k in ('codigo', 'nombre', 'categoria')):
            raise ValueError('Código, nombre y categoría son obligatorios.')
        item = TipoDocumento(empresa_id=empresa_id, codigo=data['codigo'].strip(),
                             nombre=data['nombre'].strip(), categoria=data['categoria'],
                             descripcion=data.get('descripcion', ''),
                             requiere_vencimiento=_boolean(data, 'requiere_vencimiento', False),
                             activo=_boolean(data, 'activo', True))
        item.full_clean()
        with transaction.atomic():
            item.save()
            RegistroAuditoria.objects.create(empresa_id=empresa_id, actor=request.user,
                accion='documentos.tipo.crear', entidad='TipoDocumento', entidad_id=str(item.pk), detalle={'codigo': item.codigo})
        return JsonResponse(_serialize_tipo(item), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('Ya existe un tipo de documento con ese código.', 409)


@require_http_methods(['PATCH'])
def tipo_detalle(request, empresa_id, tipo_id):
    """Actualiza el catálogo sin permitir cambiar de empresa ni borrar evidencias."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if not _authorized(request, empresa_id, 'documentos.editar'):
        return _response_error('Sin acceso.', 403)
    item = TipoDocumento.objects.filter(pk=tipo_id, empresa_id=empresa_id).first()
    if item is None:
        return _response_error('Tipo documental no encontrado.', 404)
    try:
        data = _payload(request)
        editable = {'nombre', 'descripcion', 'requiere_vencimiento', 'activo'}
        _fields(data, editable)
        if not data:
            raise ValueError('No se enviaron cambios.')
        if 'nombre' in data:
            if not isinstance(data['nombre'], str) or not data['nombre'].strip():
                raise ValueError('El nombre es obligatorio.')
            item.nombre = data['nombre'].strip()
        if 'descripcion' in data:
            if not isinstance(data['descripcion'], str):
                raise ValueError('Descripción inválida.')
            item.descripcion = data['descripcion']
        if 'requiere_vencimiento' in data:
            item.requiere_vencimiento = _boolean(data, 'requiere_vencimiento', item.requiere_vencimiento)
        if 'activo' in data:
            item.activo = _boolean(data, 'activo', item.activo)
        item.full_clean()
        with transaction.atomic():
            item.save(update_fields=list(data.keys()))
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id, actor=request.user,
                accion='documentos.tipo.editar', entidad='TipoDocumento',
                entidad_id=str(item.pk), detalle={'campos': sorted(data.keys())},
            )
        return JsonResponse(_serialize_tipo(item))
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def requisitos(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    permission = 'documentos.ver' if request.method == 'GET' else 'documentos.crear'
    if not _authorized_any_obra(request, empresa_id, permission):
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        qs = RequisitoDocumental.objects.filter(empresa_id=empresa_id).select_related('tipo_documento')
        obra_id = request.GET.get('obra_id')
        cargo_id = request.GET.get('cargo_id')
        if obra_id is not None:
            if len(obra_id) > 64 or not EmpresaObra.objects.filter(empresa_id=empresa_id, obra_id=obra_id).exists():
                return _response_error('Obra inválida.', 400)
            if not _authorized(request, empresa_id, 'documentos.ver', obra_id=obra_id):
                return _response_error('Sin acceso.', 403)
            qs = qs.filter(obra_id=obra_id)
        if cargo_id is not None:
            if len(cargo_id) > 64 or not Cargo.objects.filter(empresa_id=empresa_id, pk=cargo_id).exists():
                return _response_error('Cargo inválido.', 400)
            qs = qs.filter(cargo_id=cargo_id)
        items = []
        for item in qs[:500]:
            if item.obra_id is None or _authorized(request, empresa_id, 'documentos.ver', obra_id=item.obra_id):
                items.append(_serialize_requisito(item))
        return JsonResponse({'results': items})
    try:
        data = _payload(request)
        _fields(data, {'tipo_documento_id', 'cargo_id', 'obra_id', 'obligatorio', 'activo'})
        tipo = TipoDocumento.objects.filter(empresa_id=empresa_id, pk=data.get('tipo_documento_id')).first()
        if tipo is None:
            raise ValueError('Tipo de documento inválido.')
        cargo_id = data.get('cargo_id') or None
        obra_id = data.get('obra_id') or None
        if cargo_id and not Cargo.objects.filter(empresa_id=empresa_id, pk=cargo_id).exists():
            raise ValueError('Cargo inválido.')
        if obra_id and not EmpresaObra.objects.filter(empresa_id=empresa_id, obra_id=obra_id).exists():
            raise ValueError('Obra inválida.')
        if obra_id:
            if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
                return _response_error('Sin acceso.', 403)
        elif not _authorized(request, empresa_id, 'documentos.crear', obra_id=None):
            return _response_error('Sin acceso.', 403)
        item = RequisitoDocumental(empresa_id=empresa_id, tipo_documento=tipo,
                                  cargo_id=cargo_id, obra_id=obra_id,
                                  obligatorio=_boolean(data, 'obligatorio', True),
                                  activo=_boolean(data, 'activo', True))
        item.full_clean()
        with transaction.atomic():
            item.save()
            RegistroAuditoria.objects.create(empresa_id=empresa_id, actor=request.user,
                accion='documentos.requisito.crear', entidad='RequisitoDocumental', entidad_id=str(item.pk),
                detalle={'tipo_documento_id': str(tipo.pk)})
        return JsonResponse(_serialize_requisito(item), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('Conflicto al registrar requisito.', 409)


@require_http_methods(['PATCH'])
def requisito_detalle(request, empresa_id, requisito_id):
    """Actualizar o desactivar una regla sin alterar su alcance ni su tipo."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if not _authorized_any_obra(request, empresa_id, 'documentos.editar'):
        return _response_error('Sin acceso.', 403)
    item = RequisitoDocumental.objects.filter(pk=requisito_id, empresa_id=empresa_id).first()
    if item is None:
        return _response_error('Requisito no encontrado.', 404)
    if item.obra_id is not None:
        if not _authorized(request, empresa_id, 'documentos.editar', obra_id=item.obra_id):
            return _response_error('Sin acceso.', 403)
    elif not _authorized(request, empresa_id, 'documentos.editar', obra_id=None):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'obligatorio', 'activo'})
        if not data:
            raise ValueError('No se enviaron cambios.')
        for field in data:
            setattr(item, field, _boolean(data, field, getattr(item, field)))
        item.full_clean()
        with transaction.atomic():
            item.save(update_fields=list(data))
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id, actor=request.user,
                accion='documentos.requisito.editar', entidad='RequisitoDocumental',
                entidad_id=str(item.pk), detalle={'campos': sorted(data)},
            )
        return JsonResponse(_serialize_requisito(item))
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


# Expediente de metadatos del trabajador (sin archivos ni URLs de almacenamiento).
from datetime import date
from uuid import UUID
from django.utils import timezone
from intranet.models import Trabajador
from .models import (
    AlertaVencimiento,
    ConfiguracionAlertaEmpresa,
    DocumentoTrabajador,
    RevisionDocumentoTrabajador,
)
from .services import (
    calcular_cumplimiento_trabajador,
    calcular_vencimiento_info,
    obtener_configuracion_alertas,
    sincronizar_alertas_vencimiento,
)


def _parse_date(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError('Fecha inválida (AAAA-MM-DD).')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Fecha inválida (AAAA-MM-DD).') from exc


def _serialize_revision(rev):
    return {
        'id': str(rev.pk),
        'estado': rev.estado,
        'observaciones': rev.observaciones,
        'archivo_id': str(rev.archivo_id) if rev.archivo_id else None,
        'version': rev.archivo.version if rev.archivo_id and rev.archivo else None,
        'revisado_por_id': str(rev.revisado_por_id),
        'revisado_por_nombre': getattr(rev.revisado_por, 'name', '') or rev.revisado_por.username,
        'creado_en': rev.creado_en.isoformat(),
    }


def _serialize_documento(item):
    archivos = list(item.archivos.order_by('-version')[:1])
    ultimo_archivo = archivos[0] if archivos else None
    venc = calcular_vencimiento_info(item.fecha_vencimiento)
    return {
        'id': str(item.pk), 'trabajador_id': str(item.trabajador_id),
        'tipo_documento_id': str(item.tipo_documento_id), 'obra_id': item.obra_id,
        'fecha_emision': item.fecha_emision.isoformat() if item.fecha_emision else None,
        'fecha_vencimiento': item.fecha_vencimiento.isoformat() if item.fecha_vencimiento else None,
        'estado': item.estado, 'vencido': venc['vencido'],
        'por_vencer': venc['por_vencer'],
        'dias_restantes': venc['dias_restantes'],
        'estado_vencimiento': venc['estado_vencimiento'],
        'observaciones': item.observaciones,
        'motivo_rechazo': item.motivo_rechazo,
        'tiene_archivo': ultimo_archivo is not None,
        'version_actual': ultimo_archivo.version if ultimo_archivo else None,
        'ultimo_archivo_nombre': ultimo_archivo.nombre_original if ultimo_archivo else None,
        'version_aprobada_id': str(item.version_aprobada_id) if item.version_aprobada_id else None,
        'version_aprobada_numero': (
            item.version_aprobada.version if item.version_aprobada_id and item.version_aprobada else None
        ),
        'revisado_por_id': str(item.revisado_por_id) if item.revisado_por_id else None,
        'revisado_por_nombre': (
            (getattr(item.revisado_por, 'name', '') or item.revisado_por.username)
            if item.revisado_por_id and item.revisado_por
            else None
        ),
        'revisado_en': item.revisado_en.isoformat() if item.revisado_en else None,
        'creado_en': item.creado_en.isoformat(),
    }


@require_http_methods(['GET', 'POST'])
def documentos_trabajador(request, empresa_id, trabajador_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    permiso = 'documentos.ver' if request.method == 'GET' else 'documentos.crear'
    if not _authorized_any_obra(request, empresa_id, permiso):
        return _response_error('Sin acceso.', 403)
    if not Trabajador.objects.filter(pk=trabajador_id, empresa_id=empresa_id).exists():
        return _response_error('Trabajador no encontrado.', 404)
    if not _authorized_for_worker(request, empresa_id, trabajador_id, permiso):
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        docs = (
            DocumentoTrabajador.objects.filter(empresa_id=empresa_id, trabajador_id=trabajador_id)
            .select_related('version_aprobada', 'revisado_por')
            .prefetch_related('archivos')
            .order_by('-creado_en')[:200]
        )
        return JsonResponse({'results': [_serialize_documento(i) for i in docs if i.obra_id is None or _authorized(request, empresa_id, 'documentos.ver', obra_id=i.obra_id)]})
    try:
        data = _payload(request)
        _fields(data, {'tipo_documento_id', 'obra_id', 'fecha_emision', 'fecha_vencimiento', 'observaciones'})
        try:
            tipo_id = UUID(str(data.get('tipo_documento_id')))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Tipo documental inválido.')
        tipo = TipoDocumento.objects.filter(pk=tipo_id, empresa_id=empresa_id, categoria='trabajador', activo=True).first()
        if not tipo:
            raise ValueError('Tipo documental inválido.')
        obra_id = data.get('obra_id') or None
        if obra_id is not None:
            if not isinstance(obra_id, str) or not obra_id.strip() or len(obra_id) > 64:
                raise ValueError('Obra inválida.')
            if not EmpresaObra.objects.filter(empresa_id=empresa_id, obra_id=obra_id).exists():
                raise ValueError('Obra inválida.')
            if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
                return _response_error('Sin acceso.', 403)
        elif not _authorized_for_worker(request, empresa_id, trabajador_id, 'documentos.crear'):
            return _response_error('Sin acceso.', 403)
        observaciones = data.get('observaciones', '')
        if not isinstance(observaciones, str) or len(observaciones) > 2000:
            raise ValueError('Observaciones inválidas.')
        item = DocumentoTrabajador(
            empresa_id=empresa_id, trabajador_id=trabajador_id, tipo_documento=tipo,
            obra_id=obra_id, fecha_emision=_parse_date(data.get('fecha_emision')),
            fecha_vencimiento=_parse_date(data.get('fecha_vencimiento')),
            observaciones=observaciones, creado_por=request.user,
        )
        item.full_clean()
        with transaction.atomic():
            item.save()
            RegistroAuditoria.objects.create(empresa_id=empresa_id, actor=request.user,
                accion='documentos.trabajador.crear', entidad='DocumentoTrabajador', entidad_id=str(item.pk),
                detalle={'trabajador_id': str(trabajador_id), 'tipo_documento_id': str(tipo.pk)})
        return JsonResponse(_serialize_documento(item), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('No fue posible registrar el documento.', 409)


@require_http_methods(['PATCH'])
def revisar_documento_trabajador(request, empresa_id, trabajador_id, documento_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.aprobar')
        or _authorized_any_obra(request, empresa_id, 'documentos.editar')
    ):
        return _response_error('Sin acceso.', 403)
    item = (
        DocumentoTrabajador.objects.select_related('version_aprobada', 'revisado_por')
        .filter(pk=documento_id, empresa_id=empresa_id, trabajador_id=trabajador_id)
        .first()
    )
    if not item:
        return _response_error('Documento no encontrado.', 404)
    if not _can_review_document(request, empresa_id, trabajador_id, obra_id=item.obra_id):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'estado', 'observaciones', 'motivo_rechazo', 'archivo_id'})
        estado = data.get('estado')
        if estado == 'en_revision':
            estado = 'pendiente'
        if estado not in ('pendiente', 'aprobado', 'rechazado'):
            raise ValueError('Estado inválido.')
        observaciones = data.get('observaciones', item.observaciones)
        if not isinstance(observaciones, str) or len(observaciones) > 2000:
            raise ValueError('Observaciones inválidas.')
        motivo_rechazo = data.get('motivo_rechazo', '')
        if not isinstance(motivo_rechazo, str) or len(motivo_rechazo) > 2000:
            raise ValueError('Motivo de rechazo inválido.')

        ultimo_archivo = item.archivos.order_by('-version').first()
        archivo_objetivo = ultimo_archivo
        if data.get('archivo_id'):
            archivo_objetivo = item.archivos.filter(pk=data['archivo_id']).first()
            if archivo_objetivo is None:
                raise ValueError('La versión de archivo indicada no pertenece a este documento.')

        if estado == 'aprobado':
            if archivo_objetivo is None:
                raise ValueError('No se puede aprobar un documento sin evidencia adjunta válida.')
            version_aprobada = archivo_objetivo
            motivo_final = ''
            nota_revision = observaciones.strip()
        elif estado == 'rechazado':
            motivo_final = (motivo_rechazo.strip() or data.get('observaciones', '').strip())
            if not motivo_final:
                raise ValueError('Debes indicar el motivo del rechazo.')
            version_aprobada = None
            observaciones = motivo_final if not data.get('observaciones') else observaciones
            nota_revision = motivo_final
        else:
            version_aprobada = None
            motivo_final = ''
            nota_revision = observaciones.strip()

        with transaction.atomic():
            item.estado = estado
            item.observaciones = observaciones
            item.motivo_rechazo = motivo_final
            item.version_aprobada = version_aprobada
            item.revisado_por = request.user
            item.revisado_en = timezone.now()
            item.save(
                update_fields=[
                    'estado',
                    'observaciones',
                    'motivo_rechazo',
                    'version_aprobada',
                    'revisado_por',
                    'revisado_en',
                ]
            )
            RevisionDocumentoTrabajador.objects.create(
                documento=item,
                archivo=archivo_objetivo,
                estado=estado,
                observaciones=nota_revision,
                revisado_por=request.user,
            )
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='documentos.trabajador.revisar',
                entidad='DocumentoTrabajador',
                entidad_id=str(item.pk),
                detalle={
                    'estado': estado,
                    'version_aprobada': version_aprobada.version if version_aprobada else None,
                    'con_motivo_rechazo': bool(motivo_final),
                },
            )
        return JsonResponse(_serialize_documento(item))
    except (ValueError, TypeError) as exc:
        return _response_error(str(exc))


# Etapa 3B.2: archivos privados y versiones; credenciales nunca se envían al cliente.
import hashlib
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import httpx
from django.conf import settings
from django.db.models import Max
from django.http import FileResponse
from django.utils.text import get_valid_filename
from intranet import private_storage
from .models import ArchivoDocumentoTrabajador
from .storage import build_private_file_response


def _archivo_documento_autorizado(request, empresa_id, trabajador_id, documento_id, permiso, *, download=False):
    if _unauthenticated(request):
        return None, _response_error('Autenticación requerida.', 401)
    if download:
        has_any = (
            _authorized_any_obra(request, empresa_id, 'documentos.descargar')
            or _authorized_any_obra(request, empresa_id, 'documentos.ver')
        )
    else:
        has_any = _authorized_any_obra(request, empresa_id, permiso)
    if not has_any:
        return None, _response_error('Sin acceso.', 403)
    documento = DocumentoTrabajador.objects.filter(
        pk=documento_id, empresa_id=empresa_id, trabajador_id=trabajador_id,
        trabajador__empresa_id=empresa_id, empresa__activa=True,
    ).first()
    if documento is None:
        return None, _response_error('Documento no encontrado.', 404)
    if download:
        if not _can_download_document(request, empresa_id, trabajador_id, obra_id=documento.obra_id):
            return None, _response_error('Sin acceso.', 403)
    else:
        if documento.obra_id is not None:
            if not _authorized(request, empresa_id, permiso, obra_id=documento.obra_id):
                return None, _response_error('Sin acceso.', 403)
        elif not _authorized_for_worker(request, empresa_id, trabajador_id, permiso):
            return None, _response_error('Sin acceso.', 403)
    return documento, None


def _mime_real(data):
    if data.startswith(b'%PDF-'):
        return 'application/pdf', '.pdf'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return 'image/jpeg', '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n') and b'IEND' in data[-32:]:
        return 'image/png', '.png'
    return None, None


def _serialize_archivo(item):
    return {
        'id': str(item.pk), 'version': item.version,
        'nombre_original': item.nombre_original, 'tipo_mime': item.tipo_mime,
        'tamano_bytes': item.tamano_bytes, 'sha256': item.sha256,
        'creado_en': item.creado_en.isoformat(),
    }


@require_http_methods(['GET', 'POST'])
def archivos_documento_trabajador(request, empresa_id, trabajador_id, documento_id):
    permiso = 'documentos.ver' if request.method == 'GET' else 'documentos.editar'
    documento, error = _archivo_documento_autorizado(request, empresa_id, trabajador_id, documento_id, permiso)
    if error is not None:
        return error
    if request.method == 'GET':
        archivos = documento.archivos.order_by('-version')[:100]
        revisiones = documento.revisiones.select_related('archivo', 'revisado_por').order_by('-creado_en')[:100]
        return JsonResponse({
            'results': [_serialize_archivo(a) for a in archivos],
            'revisiones': [_serialize_revision(r) for r in revisiones],
        })

    if len(request.FILES) != 1 or 'archivo' not in request.FILES:
        return _response_error('Adjunta exactamente un archivo en el campo archivo.', 400)
    upload = request.FILES['archivo']
    max_size = min(getattr(settings, 'DOCUMENTS_MAX_FILE_SIZE', 10 * 1024 * 1024), 10 * 1024 * 1024)
    if not upload.size or upload.size > max_size:
        return _response_error('Archivo vacío o demasiado grande (máximo 10 MB).', 400)
    data = upload.read(max_size + 1)
    if not data or len(data) > max_size:
        return _response_error('Archivo vacío o demasiado grande.', 400)
    mime, extension = _mime_real(data)
    if mime is None:
        return _response_error('Solo se aceptan PDF, PNG o JPEG válidos.', 400)
    filename = get_valid_filename(Path(upload.name or 'archivo').name)[:180]
    if not filename:
        filename = 'archivo' + extension
    if Path(filename).suffix.lower() not in ('.pdf', '.png', '.jpg', '.jpeg'):
        return _response_error('Extensión no permitida.', 400)
    if {'.pdf':'application/pdf', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg'}[Path(filename).suffix.lower()] != mime:
        return _response_error('La extensión no coincide con el contenido.', 400)

    # La clave no incorpora datos personales, ni el nombre enviado por el usuario.
    key = f'documents/{empresa_id}/{documento_id}/{uuid4().hex}{extension}'
    try:
        private_storage.write_bytes(key, data, mime=mime)
    except (OSError, httpx.HTTPError, RuntimeError):
        return _response_error('No se pudo almacenar el archivo privado.', 502)

    try:
        with transaction.atomic():
            # Serialización de versiones para dos cargas concurrentes al mismo documento.
            locked = DocumentoTrabajador.objects.select_for_update().get(pk=documento.pk)
            next_version = (locked.archivos.aggregate(n=Max('version'))['n'] or 0) + 1
            item = ArchivoDocumentoTrabajador.objects.create(
                documento=locked, version=next_version, clave_privada=key,
                nombre_original=filename, tipo_mime=mime, tamano_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), subido_por=request.user,
            )
            locked.estado = 'pendiente'
            locked.version_aprobada = None
            locked.motivo_rechazo = ''
            locked.revisado_por = None
            locked.revisado_en = None
            locked.save(update_fields=['estado', 'version_aprobada', 'motivo_rechazo', 'revisado_por', 'revisado_en'])
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id, actor=request.user,
                accion='documentos.trabajador.archivo.subir', entidad='ArchivoDocumentoTrabajador',
                entidad_id=str(item.pk), detalle={'documento_id': str(documento_id), 'version': next_version},
            )
    except Exception:
        try:
            private_storage.delete(key)
        except Exception:
            pass
        raise
    return JsonResponse(_serialize_archivo(item), status=201)


@require_http_methods(['GET'])
def descargar_archivo_documento(request, empresa_id, trabajador_id, documento_id, archivo_id):
    documento, error = _archivo_documento_autorizado(
        request, empresa_id, trabajador_id, documento_id, 'documentos.descargar', download=True
    )
    if error is not None:
        return error
    item = ArchivoDocumentoTrabajador.objects.filter(documento=documento, pk=archivo_id).first()
    if item is None:
        return _response_error('Archivo no encontrado.', 404)
    try:
        data = private_storage.read_bytes(item.clave_privada)
    except FileNotFoundError:
        return _response_error('Archivo no disponible.', 404)
    except (OSError, httpx.HTTPError, RuntimeError):
        return _response_error('No se pudo recuperar el archivo privado.', 502)
    if hashlib.sha256(data).hexdigest() != item.sha256:
        return _response_error('Integridad del archivo no verificada.', 409)
    RegistroAuditoria.objects.create(
        empresa_id=empresa_id,
        actor=request.user,
        accion='documentos.trabajador.archivo.descargar',
        entidad='ArchivoDocumentoTrabajador',
        entidad_id=str(item.pk),
        detalle={'documento_id': str(documento_id), 'version': item.version},
    )
    return build_private_file_response(data, mime=item.tipo_mime, filename=item.nombre_original)


@require_http_methods(['GET'])
def cumplimiento_trabajador(request, empresa_id, trabajador_id):
    """Evalúa y retorna el cumplimiento documental automático del trabajador en el backend (Etapa 5)."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'empleados.ver')
    ):
        return _response_error('Sin acceso.', 403)
    if not Trabajador.objects.filter(pk=trabajador_id, empresa_id=empresa_id).exists():
        return _response_error('Trabajador no encontrado.', 404)
    if not (
        _authorized_for_worker(request, empresa_id, trabajador_id, 'documentos.ver')
        or _authorized_for_worker(request, empresa_id, trabajador_id, 'empleados.ver')
    ):
        return _response_error('Sin acceso.', 403)
    obra_id = request.GET.get('obra_id') or None
    if obra_id and not (
        _authorized(request, empresa_id, 'documentos.ver', obra_id=obra_id)
        or _authorized(request, empresa_id, 'empleados.ver', obra_id=obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    resumen = calcular_cumplimiento_trabajador(
        empresa_id=empresa_id,
        trabajador_id=trabajador_id,
        obra_id=obra_id,
    )
    return JsonResponse(resumen)


def _serialize_config_alertas(cfg):
    return {
        'id': str(cfg.pk),
        'empresa_id': str(cfg.empresa_id),
        'dias_anticipacion': cfg.dias_anticipacion,
        'notificar_vencidos': cfg.notificar_vencidos,
        'roles_destinatarios': cfg.roles_destinatarios,
        'activo': cfg.activo,
        'actualizado_en': cfg.actualizado_en.isoformat(),
    }


def _serialize_alerta(item):
    return {
        'id': str(item.pk),
        'empresa_id': str(item.empresa_id),
        'obra_id': item.obra_id,
        'obra_nombre': item.obra.nombre if item.obra_id and item.obra else None,
        'entidad_tipo': item.entidad_tipo,
        'entidad_id': item.entidad_id,
        'documento_id': item.documento_id,
        'titulo': item.titulo,
        'nivel': item.nivel,
        'umbral_dias': item.umbral_dias,
        'fecha_vencimiento': item.fecha_vencimiento.isoformat(),
        'dias_restantes': item.dias_restantes,
        'leida': item.leida,
        'leida_en': item.leida_en.isoformat() if item.leida_en else None,
        'creada_en': item.creada_en.isoformat(),
    }


@require_http_methods(['GET', 'PATCH', 'PUT'])
def configuracion_alertas(request, empresa_id):
    """Consulta o actualiza la configuración de alertas de vencimiento por empresa (T6.2)."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        if not (
            _authorized_any_obra(request, empresa_id, 'alertas.ver')
            or _authorized_any_obra(request, empresa_id, 'documentos.ver')
        ):
            return _response_error('Sin acceso.', 403)
        cfg = obtener_configuracion_alertas(empresa_id)
        return JsonResponse(_serialize_config_alertas(cfg))

    if not (
        _authorized(request, empresa_id, 'alertas.configurar')
        or _authorized(request, empresa_id, 'documentos.editar')
    ):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'dias_anticipacion', 'notificar_vencidos', 'roles_destinatarios', 'activo'})
        cfg = obtener_configuracion_alertas(empresa_id)
        if 'dias_anticipacion' in data:
            dias = data['dias_anticipacion']
            if (
                not isinstance(dias, list)
                or not dias
                or not all(isinstance(x, int) and 1 <= x <= 365 for x in dias)
            ):
                raise ValueError('dias_anticipacion debe ser una lista de enteros entre 1 y 365.')
            cfg.dias_anticipacion = sorted(set(dias), reverse=True)
        if 'notificar_vencidos' in data:
            cfg.notificar_vencidos = _boolean(data, 'notificar_vencidos', cfg.notificar_vencidos)
        if 'roles_destinatarios' in data:
            roles = data['roles_destinatarios']
            if not isinstance(roles, list) or not all(isinstance(r, str) and r.strip() for r in roles):
                raise ValueError('roles_destinatarios inválido.')
            cfg.roles_destinatarios = [r.strip() for r in roles]
        if 'activo' in data:
            cfg.activo = _boolean(data, 'activo', cfg.activo)
        with transaction.atomic():
            cfg.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='alertas.configuracion.editar',
                entidad='ConfiguracionAlertaEmpresa',
                entidad_id=str(cfg.pk),
                detalle={'dias_anticipacion': cfg.dias_anticipacion, 'activo': cfg.activo},
            )
        return JsonResponse(_serialize_config_alertas(cfg))
    except (ValueError, TypeError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def alertas_vencimiento(request, empresa_id):
    """Lista alertas de vencimiento dentro de Tocal o ejecuta evaluación bajo demanda (T6.3, T6.4)."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if not (
        _authorized_any_obra(request, empresa_id, 'alertas.ver')
        or _authorized_any_obra(request, empresa_id, 'documentos.ver')
    ):
        return _response_error('Sin acceso.', 403)

    if request.method == 'POST':
        resumen = sincronizar_alertas_vencimiento(empresa_id=empresa_id, actor=request.user)
        return JsonResponse(resumen)

    # Sincronización ligera al consultar
    sincronizar_alertas_vencimiento(empresa_id=empresa_id, actor=None)
    qs = AlertaVencimiento.objects.filter(empresa_id=empresa_id).select_related('obra')
    scope_docs = authorized_obra_ids(user=request.user, permission='documentos.ver', empresa_id=empresa_id)
    scope_alert = authorized_obra_ids(user=request.user, permission='alertas.ver', empresa_id=empresa_id)
    if scope_docs is not None and scope_alert is not None:
        allowed_obras = scope_docs | scope_alert
        qs = qs.filter(obra_id__in=allowed_obras)

    obra_id = request.GET.get('obra_id')
    if obra_id:
        qs = qs.filter(obra_id=obra_id)
    nivel = request.GET.get('nivel')
    if nivel in ('por_vencer', 'vencido'):
        qs = qs.filter(nivel=nivel)
    entidad_tipo = request.GET.get('entidad_tipo')
    if entidad_tipo in ('trabajador', 'empresa', 'equipo'):
        qs = qs.filter(entidad_tipo=entidad_tipo)
    leida = request.GET.get('leida')
    if leida in ('true', 'false'):
        qs = qs.filter(leida=(leida == 'true'))

    items = [_serialize_alerta(a) for a in qs[:250]]
    return JsonResponse({
        'results': items,
        'resumen': {
            'total': len(items),
            'vencidos': sum(1 for a in items if a['nivel'] == 'vencido'),
            'por_vencer': sum(1 for a in items if a['nivel'] == 'por_vencer'),
            'no_leidas': sum(1 for a in items if not a['leida']),
        },
    })


@require_http_methods(['PATCH'])
def alerta_vencimiento_detalle(request, empresa_id, alerta_id):
    """Marca una alerta como leída o no leída registrando auditoría (T6.3, T6.5)."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'alertas.ver')
        or _authorized_any_obra(request, empresa_id, 'documentos.ver')
    ):
        return _response_error('Sin acceso.', 403)
    item = AlertaVencimiento.objects.filter(pk=alerta_id, empresa_id=empresa_id).select_related('obra').first()
    if item is None:
        return _response_error('Alerta no encontrada.', 404)
    try:
        data = _payload(request)
        _fields(data, {'leida'})
        leida = _boolean(data, 'leida', True)
        with transaction.atomic():
            item.leida = leida
            item.leida_por = request.user if leida else None
            item.leida_en = timezone.now() if leida else None
            item.save(update_fields=['leida', 'leida_por', 'leida_en', 'actualizada_en'])
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='alertas.vencimiento.marcar_leida',
                entidad='AlertaVencimiento',
                entidad_id=str(item.pk),
                detalle={'leida': leida},
            )
        return JsonResponse(_serialize_alerta(item))
    except (ValueError, TypeError) as exc:
        return _response_error(str(exc))
