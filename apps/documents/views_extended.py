"""Endpoints de Etapas 7, 8, 9 y 10: Documentos de empresa, Equipos, Prevención (Capacitaciones/EPP) y Dashboards/Exportación."""
import csv
import hashlib
import io
from datetime import date
from pathlib import Path
from uuid import uuid4

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_http_methods

from apps.authorization.models import Empresa, EmpresaObra, RegistroAuditoria
from apps.authorization.permissions import authorized_obra_ids
from intranet import private_storage
from intranet.models import Cargo, Trabajador
from .models import (
    ArchivoDocumentoEmpresa,
    ArchivoDocumentoEquipo,
    AsignacionEquipoObra,
    CapacitacionTrabajador,
    CategoriaEPP,
    DocumentoEmpresa,
    DocumentoEquipo,
    EntregaEPP,
    Equipo,
    RequisitoCapacitacion,
    RevisionDocumentoEmpresa,
    RevisionDocumentoEquipo,
    TipoCapacitacion,
    TipoDocumento,
)
from .services import (
    calcular_cumplimiento_empresa,
    calcular_cumplimiento_equipo,
    calcular_dashboard_cumplimiento,
    calcular_habilitacion_preventiva,
    calcular_vencimiento_info,
    estado_documento_efectivo,
)
from .storage import build_private_file_response
from .views import (
    _authorized,
    _authorized_any_obra,
    _boolean,
    _fields,
    _mime_real,
    _payload,
    _response_error,
    _serialize_archivo,
    _unauthenticated,
)


def _parse_date(value, field_name='fecha'):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError(f'{field_name} inválida.')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'{field_name} debe tener formato YYYY-MM-DD.') from exc


def _serialize_revision_generic(rev):
    return {
        'id': str(rev.pk),
        'archivo_id': str(rev.archivo_id) if rev.archivo_id else None,
        'version_archivo': rev.archivo.version if rev.archivo_id and rev.archivo else None,
        'estado': rev.estado,
        'observaciones': rev.observaciones,
        'revisado_por_id': str(rev.revisado_por_id) if rev.revisado_por_id else None,
        'revisado_por_nombre': (
            getattr(rev.revisado_por, 'name', '') or getattr(rev.revisado_por, 'username', '')
        ) if rev.revisado_por_id else None,
        'creado_en': rev.creado_en.isoformat(),
    }


def _serialize_doc_generic(doc, extra_fields=None, ids_con_archivo=None):
    venc = calcular_vencimiento_info(doc.fecha_vencimiento)
    efectivo = estado_documento_efectivo(doc, ids_con_archivo=ids_con_archivo)
    data = {
        'id': str(doc.pk),
        'empresa_id': str(doc.empresa_id),
        'tipo_documento_id': str(doc.tipo_documento_id),
        'tipo_documento_nombre': doc.tipo_documento.nombre if doc.tipo_documento_id else '',
        'obra_id': str(doc.obra_id) if doc.obra_id else None,
        'obra_nombre': doc.obra.nombre if doc.obra_id and doc.obra else None,
        'fecha_emision': doc.fecha_emision.isoformat() if doc.fecha_emision else None,
        'fecha_vencimiento': doc.fecha_vencimiento.isoformat() if doc.fecha_vencimiento else None,
        'estado': doc.estado,
        'estado_efectivo': efectivo,
        'observaciones': doc.observaciones,
        'motivo_rechazo': doc.motivo_rechazo,
        'version_aprobada_id': str(doc.version_aprobada_id) if doc.version_aprobada_id else None,
        'version_aprobada_numero': (
            doc.version_aprobada.version if doc.version_aprobada_id and doc.version_aprobada else None
        ),
        'tiene_evidencia': (
            (doc.pk in ids_con_archivo)
            if ids_con_archivo is not None
            else (doc.version_aprobada_id is not None or doc.archivos.exists())
        ),
        'total_archivos': doc.archivos.count(),
        'vencido': venc['vencido'],
        'por_vencer': venc['por_vencer'],
        'dias_restantes': venc['dias_restantes'],
        'revisado_por_id': str(doc.revisado_por_id) if doc.revisado_por_id else None,
        'revisado_por_nombre': (
            getattr(doc.revisado_por, 'name', '') or getattr(doc.revisado_por, 'username', '')
        ) if doc.revisado_por_id else None,
        'revisado_en': doc.revisado_en.isoformat() if doc.revisado_en else None,
        'creado_en': doc.creado_en.isoformat(),
    }
    if extra_fields:
        data.update(extra_fields)
    return data


def _handle_upload(request, empresa_id, doc_model, archivo_model, doc_instance, prefix, audit_action):
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
    filename = get_valid_filename(Path(upload.name or 'archivo').name)[:180] or ('archivo' + extension)
    ext = Path(filename).suffix.lower()
    if ext not in ('.pdf', '.png', '.jpg', '.jpeg'):
        return _response_error('Extensión no permitida.', 400)
    if {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[ext] != mime:
        return _response_error('La extensión no coincide con el contenido.', 400)

    key = f'{prefix}/{empresa_id}/{doc_instance.pk}/{uuid4().hex}{extension}'
    try:
        private_storage.write_bytes(key, data, mime=mime)
    except (OSError, httpx.HTTPError, RuntimeError):
        return _response_error('No se pudo almacenar el archivo privado.', 502)

    try:
        with transaction.atomic():
            locked = doc_model.objects.select_for_update().get(pk=doc_instance.pk)
            next_version = (locked.archivos.aggregate(n=Max('version'))['n'] or 0) + 1
            item = archivo_model.objects.create(
                documento=locked,
                version=next_version,
                clave_privada=key,
                nombre_original=filename,
                tipo_mime=mime,
                tamano_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                subido_por=request.user,
            )
            locked.estado = 'pendiente'
            locked.version_aprobada = None
            locked.motivo_rechazo = ''
            locked.revisado_por = None
            locked.revisado_en = None
            locked.save(update_fields=['estado', 'version_aprobada', 'motivo_rechazo', 'revisado_por', 'revisado_en'])
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion=audit_action,
                entidad=archivo_model.__name__,
                entidad_id=str(item.pk),
                detalle={'documento_id': str(doc_instance.pk), 'version': next_version},
            )
    except Exception:
        try:
            private_storage.delete_object(key)
        except Exception:
            pass
        return _response_error('No se pudo registrar la versión del archivo.', 500)
    return JsonResponse(_serialize_archivo(item), status=201)


def _handle_review(request, empresa_id, doc_instance, revision_model, audit_action, extra_fields=None):
    try:
        data = _payload(request)
        _fields(data, {'estado', 'observaciones', 'motivo_rechazo', 'archivo_id'})
        estado = data.get('estado')
        if estado == 'en_revision':
            estado = 'pendiente'
        if estado not in ('pendiente', 'aprobado', 'rechazado'):
            raise ValueError('Estado inválido.')
        observaciones = data.get('observaciones', doc_instance.observaciones)
        if not isinstance(observaciones, str) or len(observaciones) > 2000:
            raise ValueError('Observaciones inválidas.')
        motivo_rechazo = data.get('motivo_rechazo', '')
        if not isinstance(motivo_rechazo, str) or len(motivo_rechazo) > 2000:
            raise ValueError('Motivo de rechazo inválido.')

        ultimo_archivo = doc_instance.archivos.order_by('-version').first()
        archivo_objetivo = ultimo_archivo
        if data.get('archivo_id'):
            archivo_objetivo = doc_instance.archivos.filter(pk=data['archivo_id']).first()
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
            doc_instance.estado = estado
            doc_instance.observaciones = observaciones
            doc_instance.motivo_rechazo = motivo_final
            doc_instance.version_aprobada = version_aprobada
            doc_instance.revisado_por = request.user
            doc_instance.revisado_en = timezone.now()
            doc_instance.save(
                update_fields=[
                    'estado',
                    'observaciones',
                    'motivo_rechazo',
                    'version_aprobada',
                    'revisado_por',
                    'revisado_en',
                ]
            )
            revision_model.objects.create(
                documento=doc_instance,
                archivo=archivo_objetivo,
                estado=estado,
                observaciones=nota_revision,
                revisado_por=request.user,
            )
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion=audit_action,
                entidad=doc_instance.__class__.__name__,
                entidad_id=str(doc_instance.pk),
                detalle={
                    'estado': estado,
                    'version_aprobada': version_aprobada.version if version_aprobada else None,
                },
            )
        return JsonResponse(_serialize_doc_generic(doc_instance, extra_fields=extra_fields))
    except (ValueError, TypeError) as exc:
        return _response_error(str(exc))


# ==============================================================================
# ETAPA 7 — DOCUMENTOS DE EMPRESA
# ==============================================================================

@require_http_methods(['GET', 'POST'])
def documentos_empresa(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        qs = DocumentoEmpresa.objects.filter(empresa_id=empresa_id).select_related(
            'tipo_documento', 'obra', 'version_aprobada', 'revisado_por'
        )
        obra_filter = request.GET.get('obra_id')
        if obra_filter:
            qs = qs.filter(models.Q(obra__isnull=True) | models.Q(obra_id=obra_filter))
        docs = list(qs[:300])
        ids_con_archivo = set(
            ArchivoDocumentoEmpresa.objects.filter(documento__in=docs).values_list('documento_id', flat=True)
        )
        return JsonResponse({
            'results': [_serialize_doc_generic(d, ids_con_archivo=ids_con_archivo) for d in docs]
        })

    try:
        data = _payload(request)
        _fields(data, {'tipo_documento_id', 'obra_id', 'fecha_emision', 'fecha_vencimiento', 'observaciones'})
        obra_id = data.get('obra_id') or None
        if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
            return _response_error('Sin acceso.', 403)
        tipo = TipoDocumento.objects.filter(
            pk=data.get('tipo_documento_id'),
            empresa_id=empresa_id,
            categoria='empresa',
            activo=True,
        ).first()
        if not tipo:
            return _response_error('Tipo documental de empresa inválido o inactivo.', 400)
        item = DocumentoEmpresa(
            empresa_id=empresa_id,
            tipo_documento=tipo,
            obra_id=obra_id,
            fecha_emision=_parse_date(data.get('fecha_emision'), 'fecha_emision'),
            fecha_vencimiento=_parse_date(data.get('fecha_vencimiento'), 'fecha_vencimiento'),
            observaciones=str(data.get('observaciones') or '')[:2000],
            creado_por=request.user,
        )
        item.full_clean()
        with transaction.atomic():
            item.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='documentos.empresa.crear',
                entidad='DocumentoEmpresa',
                entidad_id=str(item.pk),
                detalle={'tipo_documento_id': str(tipo.pk), 'obra_id': obra_id},
            )
        return JsonResponse(_serialize_doc_generic(item, ids_con_archivo=set()), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['PATCH'])
def revisar_documento_empresa(request, empresa_id, documento_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEmpresa.objects.select_related('tipo_documento', 'obra', 'version_aprobada', 'revisado_por').filter(
        pk=documento_id, empresa_id=empresa_id
    ).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    if not (
        _authorized(request, empresa_id, 'documentos.aprobar', obra_id=doc.obra_id)
        or _authorized(request, empresa_id, 'documentos.editar', obra_id=doc.obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    return _handle_review(request, empresa_id, doc, RevisionDocumentoEmpresa, 'documentos.empresa.revisar')


@require_http_methods(['GET', 'POST'])
def archivos_documento_empresa(request, empresa_id, documento_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEmpresa.objects.filter(pk=documento_id, empresa_id=empresa_id).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    perm = 'documentos.ver' if request.method == 'GET' else 'documentos.editar'
    if not _authorized(request, empresa_id, perm, obra_id=doc.obra_id):
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        archivos = doc.archivos.order_by('-version')[:100]
        revisiones = doc.revisiones.select_related('archivo', 'revisado_por').order_by('-creado_en')[:100]
        return JsonResponse({
            'results': [_serialize_archivo(a) for a in archivos],
            'revisiones': [_serialize_revision_generic(r) for r in revisiones],
        })
    return _handle_upload(
        request, empresa_id, DocumentoEmpresa, ArchivoDocumentoEmpresa, doc,
        'documents_company', 'documentos.empresa.archivo.subir'
    )


@require_http_methods(['GET'])
def descargar_archivo_empresa(request, empresa_id, documento_id, archivo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEmpresa.objects.filter(pk=documento_id, empresa_id=empresa_id).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    if not (
        _authorized(request, empresa_id, 'documentos.descargar', obra_id=doc.obra_id)
        or _authorized(request, empresa_id, 'documentos.ver', obra_id=doc.obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    archivo = ArchivoDocumentoEmpresa.objects.filter(pk=archivo_id, documento=doc).first()
    if not archivo:
        return _response_error('Archivo no encontrado.', 404)
    try:
        response = build_private_file_response(archivo)
    except Exception:
        return _response_error('No se pudo recuperar el archivo privado.', 502)
    RegistroAuditoria.objects.create(
        empresa_id=empresa_id,
        actor=request.user,
        accion='documentos.empresa.archivo.descargar',
        entidad='ArchivoDocumentoEmpresa',
        entidad_id=str(archivo.pk),
        detalle={'documento_id': str(doc.pk), 'version': archivo.version},
    )
    return response


@require_http_methods(['GET'])
def cumplimiento_empresa(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
        return _response_error('Sin acceso.', 403)
    obra_id = request.GET.get('obra_id') or None
    return JsonResponse(calcular_cumplimiento_empresa(empresa_id, obra_id=obra_id))


# ==============================================================================
# ETAPA 8 — EQUIPOS Y MAQUINARIA
# ==============================================================================

def _serialize_equipo(eq, comp=None):
    data = {
        'id': str(eq.pk),
        'empresa_id': str(eq.empresa_id),
        'codigo': eq.codigo,
        'nombre': eq.nombre,
        'tipo_equipo': eq.tipo_equipo,
        'marca': eq.marca,
        'modelo': eq.modelo,
        'patente_o_serie': eq.patente_o_serie,
        'estado': eq.estado,
        'activo': eq.activo,
        'creado_en': eq.creado_en.isoformat(),
    }
    if comp is not None:
        data['cumplimiento'] = comp
    return data


def _serialize_asignacion_equipo(asig):
    return {
        'id': str(asig.pk),
        'equipo_id': str(asig.equipo_id),
        'equipo_nombre': asig.equipo.nombre if asig.equipo_id else '',
        'obra_id': str(asig.obra_id),
        'obra_nombre': asig.obra.nombre if asig.obra_id and asig.obra else str(asig.obra_id),
        'responsable': asig.responsable,
        'fecha_inicio': asig.fecha_inicio.isoformat(),
        'fecha_fin': asig.fecha_fin.isoformat() if asig.fecha_fin else None,
        'observaciones': asig.observaciones,
    }


@require_http_methods(['GET', 'POST'])
def equipos(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        if not (
            _authorized_any_obra(request, empresa_id, 'equipos.ver')
            or _authorized_any_obra(request, empresa_id, 'documentos.ver')
        ):
            return _response_error('Sin acceso.', 403)
        qs = Equipo.objects.filter(empresa_id=empresa_id).order_by('nombre')
        obra_filter = request.GET.get('obra_id')
        if obra_filter:
            qs = qs.filter(asignaciones__obra_id=obra_filter).distinct()
        results = [
            _serialize_equipo(eq, calcular_cumplimiento_equipo(empresa_id, eq.pk))
            for eq in qs[:200]
        ]
        return JsonResponse({'results': results})

    if not (
        _authorized(request, empresa_id, 'equipos.crear')
        or _authorized(request, empresa_id, 'documentos.crear')
    ):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'codigo', 'nombre', 'tipo_equipo', 'marca', 'modelo', 'patente_o_serie', 'estado', 'activo'})
        eq = Equipo(
            empresa_id=empresa_id,
            codigo=str(data.get('codigo') or '').strip(),
            nombre=str(data.get('nombre') or '').strip(),
            tipo_equipo=str(data.get('tipo_equipo') or 'Maquinaria').strip(),
            marca=str(data.get('marca') or '').strip(),
            modelo=str(data.get('modelo') or '').strip(),
            patente_o_serie=str(data.get('patente_o_serie') or '').strip(),
            estado=str(data.get('estado') or 'operativo'),
            activo=_boolean(data, 'activo', True),
        )
        eq.full_clean()
        with transaction.atomic():
            eq.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='equipos.crear',
                entidad='Equipo',
                entidad_id=str(eq.pk),
                detalle={'codigo': eq.codigo, 'nombre': eq.nombre},
            )
        return JsonResponse(_serialize_equipo(eq, calcular_cumplimiento_equipo(empresa_id, eq.pk)), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('Ya existe un equipo con ese código en la empresa.', 409)


@require_http_methods(['GET', 'PATCH'])
def equipo_detalle(request, empresa_id, equipo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    eq = Equipo.objects.filter(pk=equipo_id, empresa_id=empresa_id).first()
    if not eq:
        return _response_error('Equipo no encontrado.', 404)
    if request.method == 'GET':
        if not (
            _authorized_any_obra(request, empresa_id, 'equipos.ver')
            or _authorized_any_obra(request, empresa_id, 'documentos.ver')
        ):
            return _response_error('Sin acceso.', 403)
        return JsonResponse(_serialize_equipo(eq, calcular_cumplimiento_equipo(empresa_id, eq.pk)))

    if not (
        _authorized(request, empresa_id, 'equipos.editar')
        or _authorized(request, empresa_id, 'documentos.editar')
    ):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'codigo', 'nombre', 'tipo_equipo', 'marca', 'modelo', 'patente_o_serie', 'estado', 'activo'})
        for f in ('codigo', 'nombre', 'tipo_equipo', 'marca', 'modelo', 'patente_o_serie', 'estado'):
            if f in data:
                setattr(eq, f, str(data[f] or '').strip())
        if 'activo' in data:
            eq.activo = _boolean(data, 'activo', eq.activo)
        eq.full_clean()
        with transaction.atomic():
            eq.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='equipos.editar',
                entidad='Equipo',
                entidad_id=str(eq.pk),
                detalle={'campos': sorted(data.keys())},
            )
        return JsonResponse(_serialize_equipo(eq, calcular_cumplimiento_equipo(empresa_id, eq.pk)))
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def asignaciones_equipo(request, empresa_id, equipo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    eq = Equipo.objects.filter(pk=equipo_id, empresa_id=empresa_id).first()
    if not eq:
        return _response_error('Equipo no encontrado.', 404)
    if request.method == 'GET':
        if not (
            _authorized_any_obra(request, empresa_id, 'equipos.ver')
            or _authorized_any_obra(request, empresa_id, 'documentos.ver')
        ):
            return _response_error('Sin acceso.', 403)
        items = AsignacionEquipoObra.objects.filter(empresa_id=empresa_id, equipo=eq).select_related('obra', 'equipo')
        return JsonResponse({'results': [_serialize_asignacion_equipo(a) for a in items]})

    try:
        data = _payload(request)
        _fields(data, {'obra_id', 'responsable', 'fecha_inicio', 'fecha_fin', 'observaciones'})
        obra_id = data.get('obra_id')
        if not (
            _authorized(request, empresa_id, 'equipos.editar', obra_id=obra_id)
            or _authorized(request, empresa_id, 'documentos.editar', obra_id=obra_id)
        ):
            return _response_error('Sin acceso.', 403)
        asig = AsignacionEquipoObra(
            empresa_id=empresa_id,
            equipo=eq,
            obra_id=obra_id,
            responsable=str(data.get('responsable') or '')[:160],
            fecha_inicio=_parse_date(data.get('fecha_inicio'), 'fecha_inicio'),
            fecha_fin=_parse_date(data.get('fecha_fin'), 'fecha_fin'),
            observaciones=str(data.get('observaciones') or '')[:2000],
        )
        asig.full_clean()
        with transaction.atomic():
            asig.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='equipos.asignar_obra',
                entidad='AsignacionEquipoObra',
                entidad_id=str(asig.pk),
                detalle={'equipo_id': str(eq.pk), 'obra_id': obra_id},
            )
        return JsonResponse(_serialize_asignacion_equipo(asig), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['PATCH'])
def asignacion_equipo_detalle(request, empresa_id, equipo_id, asignacion_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    asig = AsignacionEquipoObra.objects.select_related('obra', 'equipo').filter(
        pk=asignacion_id, empresa_id=empresa_id, equipo_id=equipo_id
    ).first()
    if not asig:
        return _response_error('Asignación no encontrada.', 404)
    if not (
        _authorized(request, empresa_id, 'equipos.editar', obra_id=asig.obra_id)
        or _authorized(request, empresa_id, 'documentos.editar', obra_id=asig.obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'fecha_fin', 'responsable', 'observaciones'})
        if 'fecha_fin' in data:
            asig.fecha_fin = _parse_date(data.get('fecha_fin'), 'fecha_fin')
        if 'responsable' in data:
            asig.responsable = str(data.get('responsable') or '')[:160]
        if 'observaciones' in data:
            asig.observaciones = str(data.get('observaciones') or '')[:2000]
        asig.full_clean()
        asig.save()
        return JsonResponse(_serialize_asignacion_equipo(asig))
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def documentos_equipo(request, empresa_id, equipo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    eq = Equipo.objects.filter(pk=equipo_id, empresa_id=empresa_id).first()
    if not eq:
        return _response_error('Equipo no encontrado.', 404)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        docs = list(
            DocumentoEquipo.objects.filter(empresa_id=empresa_id, equipo=eq)
            .select_related('tipo_documento', 'obra', 'version_aprobada', 'revisado_por')[:200]
        )
        ids_con_archivo = set(
            ArchivoDocumentoEquipo.objects.filter(documento__in=docs).values_list('documento_id', flat=True)
        )
        return JsonResponse({
            'results': [
                _serialize_doc_generic(d, extra_fields={'equipo_id': str(eq.pk)}, ids_con_archivo=ids_con_archivo)
                for d in docs
            ]
        })

    try:
        data = _payload(request)
        _fields(data, {'tipo_documento_id', 'obra_id', 'fecha_emision', 'fecha_vencimiento', 'observaciones'})
        obra_id = data.get('obra_id') or None
        if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
            return _response_error('Sin acceso.', 403)
        tipo = TipoDocumento.objects.filter(
            pk=data.get('tipo_documento_id'),
            empresa_id=empresa_id,
            categoria='equipo',
            activo=True,
        ).first()
        if not tipo:
            return _response_error('Tipo documental de equipo inválido o inactivo.', 400)
        doc = DocumentoEquipo(
            empresa_id=empresa_id,
            equipo=eq,
            tipo_documento=tipo,
            obra_id=obra_id,
            fecha_emision=_parse_date(data.get('fecha_emision'), 'fecha_emision'),
            fecha_vencimiento=_parse_date(data.get('fecha_vencimiento'), 'fecha_vencimiento'),
            observaciones=str(data.get('observaciones') or '')[:2000],
            creado_por=request.user,
        )
        doc.full_clean()
        with transaction.atomic():
            doc.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='documentos.equipo.crear',
                entidad='DocumentoEquipo',
                entidad_id=str(doc.pk),
                detalle={'equipo_id': str(eq.pk), 'tipo_documento_id': str(tipo.pk)},
            )
        return JsonResponse(
            _serialize_doc_generic(doc, extra_fields={'equipo_id': str(eq.pk)}, ids_con_archivo=set()),
            status=201,
        )
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['PATCH'])
def revisar_documento_equipo(request, empresa_id, equipo_id, documento_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEquipo.objects.select_related('tipo_documento', 'obra', 'version_aprobada', 'revisado_por').filter(
        pk=documento_id, empresa_id=empresa_id, equipo_id=equipo_id
    ).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    if not (
        _authorized(request, empresa_id, 'documentos.aprobar', obra_id=doc.obra_id)
        or _authorized(request, empresa_id, 'documentos.editar', obra_id=doc.obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    return _handle_review(
        request, empresa_id, doc, RevisionDocumentoEquipo, 'documentos.equipo.revisar',
        extra_fields={'equipo_id': str(equipo_id)}
    )


@require_http_methods(['GET', 'POST'])
def archivos_documento_equipo(request, empresa_id, equipo_id, documento_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEquipo.objects.filter(pk=documento_id, empresa_id=empresa_id, equipo_id=equipo_id).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    perm = 'documentos.ver' if request.method == 'GET' else 'documentos.editar'
    if not _authorized(request, empresa_id, perm, obra_id=doc.obra_id):
        return _response_error('Sin acceso.', 403)
    if request.method == 'GET':
        archivos = doc.archivos.order_by('-version')[:100]
        revisiones = doc.revisiones.select_related('archivo', 'revisado_por').order_by('-creado_en')[:100]
        return JsonResponse({
            'results': [_serialize_archivo(a) for a in archivos],
            'revisiones': [_serialize_revision_generic(r) for r in revisiones],
        })
    return _handle_upload(
        request, empresa_id, DocumentoEquipo, ArchivoDocumentoEquipo, doc,
        'documents_equipment', 'documentos.equipo.archivo.subir'
    )


@require_http_methods(['GET'])
def descargar_archivo_equipo(request, empresa_id, equipo_id, documento_id, archivo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    doc = DocumentoEquipo.objects.filter(pk=documento_id, empresa_id=empresa_id, equipo_id=equipo_id).first()
    if not doc:
        return _response_error('Documento no encontrado.', 404)
    if not (
        _authorized(request, empresa_id, 'documentos.descargar', obra_id=doc.obra_id)
        or _authorized(request, empresa_id, 'documentos.ver', obra_id=doc.obra_id)
    ):
        return _response_error('Sin acceso.', 403)
    archivo = ArchivoDocumentoEquipo.objects.filter(pk=archivo_id, documento=doc).first()
    if not archivo:
        return _response_error('Archivo no encontrado.', 404)
    try:
        response = build_private_file_response(archivo)
    except Exception:
        return _response_error('No se pudo recuperar el archivo privado.', 502)
    RegistroAuditoria.objects.create(
        empresa_id=empresa_id,
        actor=request.user,
        accion='documentos.equipo.archivo.descargar',
        entidad='ArchivoDocumentoEquipo',
        entidad_id=str(archivo.pk),
        detalle={'documento_id': str(doc.pk), 'version': archivo.version},
    )
    return response


@require_http_methods(['GET'])
def cumplimiento_equipo(request, empresa_id, equipo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
        return _response_error('Sin acceso.', 403)
    obra_id = request.GET.get('obra_id') or None
    return JsonResponse(calcular_cumplimiento_equipo(empresa_id, equipo_id, obra_id=obra_id))


# ==============================================================================
# ETAPA 9 — CAPACITACIONES, EPP Y PREVENCIÓN
# ==============================================================================

def _serialize_tipo_cap(t):
    return {
        'id': str(t.pk),
        'codigo': t.codigo,
        'nombre': t.nombre,
        'descripcion': t.descripcion,
        'horas_sugeridas': t.horas_sugeridas,
        'requiere_vencimiento': t.requiere_vencimiento,
        'vigencia_meses': t.vigencia_meses,
        'activo': t.activo,
    }


def _serialize_req_cap(r):
    return {
        'id': str(r.pk),
        'tipo_capacitacion_id': str(r.tipo_capacitacion_id),
        'tipo_capacitacion_nombre': r.tipo_capacitacion.nombre if r.tipo_capacitacion_id else '',
        'cargo_id': r.cargo_id,
        'cargo_nombre': r.cargo.nombre if r.cargo_id and r.cargo else None,
        'obra_id': r.obra_id,
        'obra_nombre': r.obra.nombre if r.obra_id and r.obra else None,
        'obligatorio': r.obligatorio,
        'activo': r.activo,
    }


def _serialize_cap_trab(c):
    return {
        'id': str(c.pk),
        'trabajador_id': c.trabajador_id,
        'trabajador_nombre': f'{c.trabajador.nombres} {c.trabajador.apellido_paterno}'.strip() if c.trabajador_id else '',
        'tipo_capacitacion_id': str(c.tipo_capacitacion_id),
        'tipo_capacitacion_nombre': c.tipo_capacitacion.nombre if c.tipo_capacitacion_id else '',
        'obra_id': c.obra_id,
        'obra_nombre': c.obra.nombre if c.obra_id and c.obra else None,
        'fecha_realizacion': c.fecha_realizacion.isoformat(),
        'fecha_vencimiento': c.fecha_vencimiento.isoformat() if c.fecha_vencimiento else None,
        'horas': c.horas,
        'relator': c.relator,
        'estado': c.estado,
        'observaciones': c.observaciones,
    }


def _serialize_cat_epp(cat):
    return {
        'id': str(cat.pk),
        'codigo': cat.codigo,
        'nombre': cat.nombre,
        'descripcion': cat.descripcion,
        'vida_util_meses': cat.vida_util_meses,
        'requiere_vencimiento': cat.requiere_vencimiento,
        'obligatorio_terreno': cat.obligatorio_terreno,
        'activo': cat.activo,
    }


def _serialize_entrega_epp(e):
    return {
        'id': str(e.pk),
        'trabajador_id': e.trabajador_id,
        'trabajador_nombre': f'{e.trabajador.nombres} {e.trabajador.apellido_paterno}'.strip() if e.trabajador_id else '',
        'categoria_epp_id': str(e.categoria_epp_id),
        'categoria_epp_nombre': e.categoria_epp.nombre if e.categoria_epp_id else '',
        'obra_id': e.obra_id,
        'obra_nombre': e.obra.nombre if e.obra_id and e.obra else None,
        'elemento': e.elemento,
        'talla_o_serie': e.talla_o_serie,
        'cantidad': e.cantidad,
        'fecha_entrega': e.fecha_entrega.isoformat(),
        'fecha_vencimiento': e.fecha_vencimiento.isoformat() if e.fecha_vencimiento else None,
        'estado': e.estado,
        'firmado_recepcion': e.firmado_recepcion,
        'observaciones': e.observaciones,
    }


@require_http_methods(['GET', 'POST'])
def tipos_capacitacion(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        items = TipoCapacitacion.objects.filter(empresa_id=empresa_id).order_by('nombre')
        return JsonResponse({'results': [_serialize_tipo_cap(t) for t in items]})
    if not _authorized(request, empresa_id, 'documentos.crear'):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'codigo', 'nombre', 'descripcion', 'horas_sugeridas', 'horas_duracion', 'requiere_vencimiento', 'vigencia_meses', 'activo'})
        horas = int(data.get('horas_sugeridas') or data.get('horas_duracion') or 1)
        t = TipoCapacitacion(
            empresa_id=empresa_id,
            codigo=str(data.get('codigo') or '').strip(),
            nombre=str(data.get('nombre') or '').strip(),
            descripcion=str(data.get('descripcion') or '').strip(),
            horas_sugeridas=horas,
            requiere_vencimiento=_boolean(data, 'requiere_vencimiento', True),
            vigencia_meses=int(data.get('vigencia_meses') or 12),
            activo=_boolean(data, 'activo', True),
        )
        t.full_clean()
        t.save()
        return JsonResponse(_serialize_tipo_cap(t), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('Código de capacitación duplicado en la empresa.', 409)


@require_http_methods(['PATCH'])
def tipo_capacitacion_detalle(request, empresa_id, tipo_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not _authorized(request, empresa_id, 'documentos.editar'):
        return _response_error('Sin acceso.', 403)
    t = TipoCapacitacion.objects.filter(pk=tipo_id, empresa_id=empresa_id).first()
    if not t:
        return _response_error('No encontrado.', 404)
    try:
        data = _payload(request)
        if 'nombre' in data:
            t.nombre = str(data['nombre'] or '').strip()
        if 'descripcion' in data:
            t.descripcion = str(data['descripcion'] or '').strip()
        if 'horas_sugeridas' in data:
            t.horas_sugeridas = int(data['horas_sugeridas'] or 1)
        if 'requiere_vencimiento' in data:
            t.requiere_vencimiento = _boolean(data, 'requiere_vencimiento', t.requiere_vencimiento)
        if 'vigencia_meses' in data:
            t.vigencia_meses = int(data['vigencia_meses'] or 12)
        if 'activo' in data:
            t.activo = _boolean(data, 'activo', t.activo)
        t.full_clean()
        t.save()
        return JsonResponse(_serialize_tipo_cap(t))
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def requisitos_capacitacion(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        items = RequisitoCapacitacion.objects.filter(empresa_id=empresa_id).select_related('tipo_capacitacion', 'cargo', 'obra')
        return JsonResponse({'results': [_serialize_req_cap(r) for r in items]})
    if not _authorized(request, empresa_id, 'documentos.crear'):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'tipo_capacitacion_id', 'cargo_id', 'obra_id', 'obligatorio', 'activo'})
        r = RequisitoCapacitacion(
            empresa_id=empresa_id,
            tipo_capacitacion_id=data.get('tipo_capacitacion_id'),
            cargo_id=data.get('cargo_id') or None,
            obra_id=data.get('obra_id') or None,
            obligatorio=_boolean(data, 'obligatorio', True),
            activo=_boolean(data, 'activo', True),
        )
        r.full_clean()
        r.save()
        return JsonResponse(_serialize_req_cap(r), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def capacitaciones_trabajador(request, empresa_id, trabajador_id=None):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        qs = CapacitacionTrabajador.objects.filter(empresa_id=empresa_id).select_related(
            'trabajador', 'tipo_capacitacion', 'obra'
        )
        tid = trabajador_id or request.GET.get('trabajador_id')
        if tid:
            qs = qs.filter(trabajador_id=tid)
        if request.GET.get('obra_id'):
            qs = qs.filter(obra_id=request.GET['obra_id'])
        return JsonResponse({'results': [_serialize_cap_trab(c) for c in qs[:300]]})

    try:
        data = _payload(request)
        _fields(data, {
            'trabajador_id', 'tipo_capacitacion_id', 'obra_id', 'fecha_realizacion',
            'fecha_vencimiento', 'horas', 'relator', 'estado', 'observaciones',
            'calificacion', 'aprobado', 'firmado_asistencia',
        })
        obra_id = data.get('obra_id') or None
        if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
            return _response_error('Sin acceso.', 403)
        tc_obj = TipoCapacitacion.objects.filter(pk=data.get('tipo_capacitacion_id'), empresa_id=empresa_id).first()
        f_real = _parse_date(data.get('fecha_realizacion'), 'fecha_realizacion')
        f_venc = _parse_date(data.get('fecha_vencimiento'), 'fecha_vencimiento')
        if not f_venc and f_real and tc_obj and tc_obj.requiere_vencimiento and tc_obj.vigencia_meses:
            from datetime import timedelta
            f_venc = f_real + timedelta(days=int(tc_obj.vigencia_meses) * 30)
        obs_parts = []
        if data.get('calificacion') not in (None, ''):
            obs_parts.append(f"Evaluación: {data['calificacion']}%")
        if 'aprobado' in data:
            obs_parts.append("Resultado: Aprobado" if data['aprobado'] else "Resultado: Reprobado")
        if 'firmado_asistencia' in data:
            obs_parts.append("Asistencia firmada" if data['firmado_asistencia'] else "Sin firma")
        if data.get('observaciones'):
            obs_parts.append(str(data['observaciones']).strip())
        c = CapacitacionTrabajador(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id or data.get('trabajador_id'),
            tipo_capacitacion_id=data.get('tipo_capacitacion_id'),
            obra_id=obra_id,
            fecha_realizacion=f_real,
            fecha_vencimiento=f_venc,
            horas=int(data.get('horas') or (tc_obj.horas_sugeridas if tc_obj else 1)),
            relator=str(data.get('relator') or '')[:160],
            estado=str(data.get('estado') or ('observada' if data.get('aprobado') is False else 'vigente')),
            observaciones=' | '.join(obs_parts)[:2000],
            registrado_por=request.user,
        )
        c.full_clean()
        with transaction.atomic():
            c.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='prevencion.capacitacion.registrar',
                entidad='CapacitacionTrabajador',
                entidad_id=str(c.pk),
                detalle={'trabajador_id': c.trabajador_id, 'tipo_capacitacion_id': str(c.tipo_capacitacion_id)},
            )
        return JsonResponse(_serialize_cap_trab(c), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def categorias_epp(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        items = CategoriaEPP.objects.filter(empresa_id=empresa_id).order_by('nombre')
        return JsonResponse({'results': [_serialize_cat_epp(c) for c in items]})
    if not _authorized(request, empresa_id, 'documentos.crear'):
        return _response_error('Sin acceso.', 403)
    try:
        data = _payload(request)
        _fields(data, {'codigo', 'nombre', 'descripcion', 'vida_util_meses', 'vida_util_dias', 'requiere_vencimiento', 'obligatorio_terreno', 'activo'})
        vida_meses = int(data.get('vida_util_meses') or (max(1, int(data['vida_util_dias']) // 30) if data.get('vida_util_dias') else 6))
        cat = CategoriaEPP(
            empresa_id=empresa_id,
            codigo=str(data.get('codigo') or '').strip(),
            nombre=str(data.get('nombre') or '').strip(),
            descripcion=str(data.get('descripcion') or '').strip(),
            vida_util_meses=vida_meses,
            requiere_vencimiento=_boolean(data, 'requiere_vencimiento', False),
            obligatorio_terreno=_boolean(data, 'obligatorio_terreno', True),
            activo=_boolean(data, 'activo', True),
        )
        cat.full_clean()
        cat.save()
        return JsonResponse(_serialize_cat_epp(cat), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))
    except IntegrityError:
        return _response_error('Código de categoría EPP duplicado en la empresa.', 409)


@require_http_methods(['GET', 'POST'])
def entregas_epp(request, empresa_id, trabajador_id=None):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not _authorized_any_obra(request, empresa_id, 'documentos.ver'):
            return _response_error('Sin acceso.', 403)
        qs = EntregaEPP.objects.filter(empresa_id=empresa_id).select_related('trabajador', 'categoria_epp', 'obra')
        tid = trabajador_id or request.GET.get('trabajador_id')
        if tid:
            qs = qs.filter(trabajador_id=tid)
        if request.GET.get('obra_id'):
            qs = qs.filter(obra_id=request.GET['obra_id'])
        return JsonResponse({'results': [_serialize_entrega_epp(e) for e in qs[:300]]})

    try:
        data = _payload(request)
        _fields(data, {
            'trabajador_id', 'categoria_epp_id', 'categoria_id', 'obra_id', 'elemento', 'descripcion_elemento',
            'talla_o_serie', 'talla', 'cantidad', 'fecha_entrega', 'fecha_vencimiento', 'estado',
            'firmado_recepcion', 'observaciones',
        })
        obra_id = data.get('obra_id') or None
        if not _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id):
            return _response_error('Sin acceso.', 403)
        cat_id = data.get('categoria_epp_id') or data.get('categoria_id')
        cat_obj = CategoriaEPP.objects.filter(pk=cat_id, empresa_id=empresa_id).first() if cat_id else None
        elem_str = str(data.get('elemento') or data.get('descripcion_elemento') or (cat_obj.nombre if cat_obj else 'EPP')).strip()[:180]
        talla_str = str(data.get('talla_o_serie') or data.get('talla') or '').strip()[:80]
        e = EntregaEPP(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id or data.get('trabajador_id'),
            categoria_epp_id=cat_id,
            obra_id=obra_id,
            elemento=elem_str,
            talla_o_serie=talla_str,
            cantidad=int(data.get('cantidad') or 1),
            fecha_entrega=_parse_date(data.get('fecha_entrega'), 'fecha_entrega'),
            fecha_vencimiento=_parse_date(data.get('fecha_vencimiento'), 'fecha_vencimiento'),
            estado=str(data.get('estado') or 'entregado'),
            firmado_recepcion=_boolean(data, 'firmado_recepcion', True),
            observaciones=str(data.get('observaciones') or '')[:2000],
            entregado_por=request.user,
        )
        e.full_clean()
        with transaction.atomic():
            e.save()
            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='prevencion.epp.entregar',
                entidad='EntregaEPP',
                entidad_id=str(e.pk),
                detalle={'trabajador_id': e.trabajador_id, 'elemento': e.elemento},
            )
        return JsonResponse(_serialize_entrega_epp(e), status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET'])
def habilitacion_preventiva(request, empresa_id, trabajador_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'empleados.ver')
    ):
        return _response_error('Sin acceso.', 403)
    if not Trabajador.objects.filter(pk=trabajador_id, empresa_id=empresa_id).exists():
        return _response_error('Trabajador no encontrado.', 404)
    obra_id = request.GET.get('obra_id') or None
    return JsonResponse(calcular_habilitacion_preventiva(empresa_id, trabajador_id, obra_id=obra_id))


# ==============================================================================
# ETAPA 10 — DASHBOARD DE CUMPLIMIENTO Y EXPORTACIÓN CSV/EXCEL
# ==============================================================================

@require_http_methods(['GET'])
def dashboard_cumplimiento(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'informes.ver')
        or _authorized_any_obra(request, empresa_id, 'obras.ver')
    ):
        return _response_error('Sin acceso.', 403)
    scope = authorized_obra_ids(user=request.user, permission='documentos.ver', empresa_id=empresa_id)
    if scope == set():
        scope = authorized_obra_ids(user=request.user, permission='obras.ver', empresa_id=empresa_id)
    obra_id = request.GET.get('obra_id') or None
    if obra_id and scope is not None and obra_id not in scope:
        return _response_error('Sin acceso a la obra solicitada.', 403)
    cargo_id = request.GET.get('cargo_id') or None
    estado_filtro = request.GET.get('estado') or None
    data = calcular_dashboard_cumplimiento(
        empresa_id,
        obra_id=obra_id,
        cargo_id=cargo_id,
        estado_filtro=estado_filtro,
        authorized_obras=scope,
    )
    return JsonResponse(data)


@require_http_methods(['GET'])
def exportar_cumplimiento_csv(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'informes.exportar')
    ):
        return _response_error('Sin acceso para exportar información.', 403)
    scope = authorized_obra_ids(user=request.user, permission='documentos.ver', empresa_id=empresa_id)
    obra_id = request.GET.get('obra_id') or None
    if obra_id and scope is not None and obra_id not in scope:
        return _response_error('Sin acceso a la obra solicitada.', 403)
    cargo_id = request.GET.get('cargo_id') or None
    estado_filtro = request.GET.get('estado') or None

    data = calcular_dashboard_cumplimiento(
        empresa_id,
        obra_id=obra_id,
        cargo_id=cargo_id,
        estado_filtro=estado_filtro,
        authorized_obras=scope,
    )

    buffer = io.StringIO()
    buffer.write('\ufeff')  # BOM UTF-8 para compatibilidad directa con Microsoft Excel
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow([
        'ID Trabajador',
        'Nombre Completo',
        'Porcentaje Cumplimiento (%)',
        'Requisitos Obligatorios',
        'Aprobados',
        'Pendientes',
        'Rechazados',
        'Vencidos',
        'Faltantes',
        'Habilitado Documentalmente',
        'Estado Preventivo Integral',
    ])
    for row in data['trabajadores']:
        writer.writerow([
            row['trabajador_id'],
            row['nombre'],
            row['porcentaje_cumplimiento'],
            row['total_obligatorios'],
            row['aprobados'],
            row['pendientes'],
            row['rechazados'],
            row['vencidos'],
            row['faltantes'],
            'SI' if row['habilitado_documentalmente'] else 'NO',
            row['estado_preventivo_label'],
        ])

    RegistroAuditoria.objects.create(
        empresa_id=empresa_id,
        actor=request.user,
        accion='cumplimiento.exportar_csv',
        entidad='Empresa',
        entidad_id=str(empresa_id),
        detalle={'obra_id': obra_id, 'filas': len(data['trabajadores'])},
    )

    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="cumplimiento_tocal_{data["fecha_corte"]}.csv"'
    return response


@require_http_methods(['POST'])
def sembrar_catalogos_tocal_view(request, empresa_id):
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return _response_error('Sin acceso.', 403)
    if not (
        _authorized(request, empresa_id, 'tipos_documentales.crear')
        or _authorized(request, empresa_id, 'documentos.crear')
        or _authorized(request, empresa_id, 'cargos.crear')
    ):
        return _response_error('Sin acceso para poblar catálogos base.', 403)
    from .seed_tocal import sembrar_catalogos_base_tocal

    resumen = sembrar_catalogos_base_tocal(empresa_id, actor=request.user)
    return JsonResponse(resumen)


# ==============================================================================
# RF-06, RF-12, RF-15, RF-16 — HOMBRE NUEVO, CHECKLISTS, TERRENO Y DOSSIER FUF/DS44
# ==============================================================================

@require_http_methods(['POST'])
def registrar_kit_hombre_nuevo(request, empresa_id, trabajador_id):
    """RF-06: Proceso de incorporación «Hombre Nuevo» (Inducción ODI/IRL + RIOHS + Contrato + Kit EPP básico)."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    trabajador = Trabajador.objects.filter(pk=trabajador_id, empresa_id=empresa_id).first()
    if not trabajador:
        return _response_error('Trabajador no encontrado.', 404)
    try:
        data = _payload(request) if request.body else {}
        obra_id = data.get('obra_id') or None
        if not (
            _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id)
            or _authorized(request, empresa_id, 'empleados.editar', obra_id=obra_id)
        ):
            return _response_error('Sin acceso.', 403)
        from datetime import timedelta
        from .seed_tocal import sembrar_catalogos_base_tocal
        from .models import DocumentoTrabajador

        hoy = _parse_date(data.get('fecha_ingreso'), 'fecha_ingreso') or timezone.localdate()
        relator = str(data.get('relator') or request.user.name or request.user.get_username())[:160]
        calificacion = data.get('calificacion', 100)

        # Garantizar que los tipos base existan en la empresa
        if not TipoDocumento.objects.filter(empresa_id=empresa_id, codigo='contrato-trabajo').exists():
            sembrar_catalogos_base_tocal(empresa_id, actor=request.user)

        docs_creados = 0
        cap_creadas = 0
        epp_creados = 0

        with transaction.atomic():
            # 1. Expedientes base de ingreso (Contrato, Cédula, RIOHS, ODI/IRL)
            for cod_doc in ('contrato-trabajo', 'cedula-identidad', 'recepcion-riohs', 'odi-das-ds44'):
                td = TipoDocumento.objects.filter(empresa_id=empresa_id, codigo=cod_doc, activo=True).first()
                if td and not DocumentoTrabajador.objects.filter(
                    empresa_id=empresa_id, trabajador=trabajador, tipo_documento=td
                ).exists():
                    venc = (hoy + timedelta(days=365)) if td.requiere_vencimiento else None
                    doc = DocumentoTrabajador(
                        empresa_id=empresa_id,
                        trabajador=trabajador,
                        tipo_documento=td,
                        obra_id=obra_id,
                        fecha_emision=hoy,
                        fecha_vencimiento=venc,
                        estado='pendiente',
                        observaciones='Generado en proceso de Carpeta de Ingreso «Hombre Nuevo» (RF-06). Pendiente adjuntar respaldo firmado.',
                        creado_por=request.user,
                    )
                    doc.save()
                    docs_creados += 1

            # 2. Capacitación Inducción Hombre Nuevo + ODI (DS 44)
            tc_ind = TipoCapacitacion.objects.filter(empresa_id=empresa_id, codigo='induccion-odi-ds44').first()
            if tc_ind and not CapacitacionTrabajador.objects.filter(
                empresa_id=empresa_id, trabajador=trabajador, tipo_capacitacion=tc_ind, estado='vigente'
            ).exists():
                CapacitacionTrabajador.objects.create(
                    empresa_id=empresa_id,
                    trabajador=trabajador,
                    tipo_capacitacion=tc_ind,
                    obra_id=obra_id,
                    fecha_realizacion=hoy,
                    fecha_vencimiento=hoy + timedelta(days=365),
                    horas=tc_ind.horas_sugeridas or 4,
                    relator=relator,
                    estado='vigente',
                    observaciones=f'Inducción Hombre Nuevo + ODI/IRL (RF-06) | Evaluación: {calificacion}% | Resultado: Aprobado | Asistencia firmada',
                    registrado_por=request.user,
                )
                cap_creadas += 1

            # 3. Entrega inicial de Kit EPP Básico obligatorio en terreno
            cats_basicas = CategoriaEPP.objects.filter(
                empresa_id=empresa_id, activo=True, obligatorio_terreno=True
            )
            for cat in cats_basicas:
                if not EntregaEPP.objects.filter(
                    empresa_id=empresa_id, trabajador=trabajador, categoria_epp=cat, estado__in=('entregado', 'renovado')
                ).exists():
                    EntregaEPP.objects.create(
                        empresa_id=empresa_id,
                        trabajador=trabajador,
                        categoria_epp=cat,
                        obra_id=obra_id,
                        elemento=cat.nombre,
                        talla_o_serie='Estándar',
                        cantidad=1,
                        fecha_entrega=hoy,
                        fecha_vencimiento=hoy + timedelta(days=(cat.vida_util_meses or 6) * 30),
                        estado='entregado',
                        firmado_recepcion=True,
                        observaciones='Kit inicial «Hombre Nuevo» (RF-06). Recepción firmada por el trabajador.',
                        entregado_por=request.user,
                    )
                    epp_creados += 1

            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='prevencion.hombre_nuevo.registrar',
                entidad='Trabajador',
                entidad_id=str(trabajador.pk),
                detalle={
                    'documentos_inicializados': docs_creados,
                    'induccion_registrada': cap_creadas,
                    'epp_entregados': epp_creados,
                },
            )

        return JsonResponse({
            'trabajador_id': str(trabajador.pk),
            'documentos_inicializados': docs_creados,
            'induccion_registrada': cap_creadas,
            'epp_entregados': epp_creados,
            'habilitacion': calcular_habilitacion_preventiva(empresa_id, trabajador.pk, obra_id=obra_id),
        }, status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET'])
def consulta_terreno_rf15(request, empresa_id):
    """RF-15: Consulta rápida en terreno por nombre, apellido, RUT o cargo."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'empleados.ver')
        or _authorized_any_obra(request, empresa_id, 'obras.ver')
    ):
        return _response_error('Sin acceso.', 403)

    from django.db import models as dj_models
    from intranet.models import AsignacionTrabajadorObra
    from apps.authorization.permissions import has_any_obra_permission

    q = (request.GET.get('q') or '').strip()
    obra_id = request.GET.get('obra_id') or None
    hoy = timezone.localdate()

    qs = Trabajador.objects.filter(empresa_id=empresa_id, activo=True)
    if obra_id:
        qs = qs.filter(asignaciones_obras__obra_id=obra_id).distinct()
    if q:
        q_clean = q.upper().replace('TOCAL-', '').strip()
        q_filter = (
            dj_models.Q(nombres__icontains=q)
            | dj_models.Q(apellido_paterno__icontains=q)
            | dj_models.Q(apellido_materno__icontains=q)
            | dj_models.Q(rut__icontains=q)
            | dj_models.Q(asignaciones_obras__cargo__nombre__icontains=q)
        )
        if q_clean.isdigit():
            q_filter = q_filter | dj_models.Q(pk=int(q_clean))
        qs = qs.filter(q_filter).distinct()

    sensitive = has_any_obra_permission(
        user=request.user,
        permission='empleados.ver_sensibles',
        empresa_id=empresa_id,
    )

    resultados = []
    for w in qs.order_by('apellido_paterno', 'nombres')[:40]:
        prev = calcular_habilitacion_preventiva(empresa_id, w.pk, obra_id=obra_id, hoy=hoy)
        asigs = (
            AsignacionTrabajadorObra.objects.filter(
                empresa_id=empresa_id, trabajador=w, fecha_inicio__lte=hoy
            )
            .filter(dj_models.Q(fecha_fin__isnull=True) | dj_models.Q(fecha_fin__gte=hoy))
            .select_related('obra', 'cargo')
        )
        resultados.append({
            'id': w.pk,
            'qr_codigo': f"TOCAL-{str(w.pk).zfill(4)}",
            'nombre': f"{w.nombres} {w.apellido_paterno} {w.apellido_materno}".strip(),
            'rut': w.rut if sensitive else None,
            'asignaciones_activas': [
                {'obra_id': a.obra_id, 'obra_nombre': a.obra.nombre, 'cargo_nombre': a.cargo.nombre}
                for a in asigs
            ],
            'estado_habilitacion': prev['estado_habilitacion'],
            'estado_label': prev['estado_label'],
            'observaciones': prev['observaciones'],
            'documental': prev['documental'],
            'capacitaciones': prev['capacitaciones'],
            'epp': prev['epp'],
        })

    return JsonResponse({
        'results': resultados,
        'total': len(resultados),
        'resumen_pts': _build_resumen_pts(empresa_id, qs, hoy),
    })


def _build_resumen_pts(empresa_id, trabajadores_qs, hoy):
    """RF-07: Calcula semáforo de cobertura de Procedimientos de Trabajo Seguro (PTS) e Inducciones ODI."""
    pts_types = list(
        TipoCapacitacion.objects.filter(empresa_id=empresa_id, activo=True).order_by('nombre')
    )
    worker_ids = list(trabajadores_qs.values_list('id', flat=True))
    total_workers = len(worker_ids)
    resumen = []
    for t in pts_types:
        cubiertos = (
            CapacitacionTrabajador.objects.filter(
                empresa_id=empresa_id,
                tipo_capacitacion=t,
                trabajador_id__in=worker_ids,
                estado='vigente',
            )
            .exclude(fecha_vencimiento__lt=hoy)
            .values('trabajador_id')
            .distinct()
            .count()
        ) if total_workers else 0
        pct = round((cubiertos / total_workers) * 100) if total_workers else 100
        resumen.append({
            'id': str(t.pk),
            'codigo': t.codigo,
            'nombre': t.nombre,
            'cubiertos': cubiertos,
            'total_trabajadores': total_workers,
            'pendientes': max(0, total_workers - cubiertos),
            'porcentaje': pct,
            'semaforo': 'verde' if pct >= 85 else ('amarillo' if pct >= 50 else 'rojo'),
        })
    return resumen


@require_http_methods(['POST'])
def charla_diaria_cuadrilla_rf08(request, empresa_id):
    """RF-08 / DS 44: Registra Charla Operacional Diaria de 5 Minutos / AST o Difusión PTS masiva a una cuadrilla."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.crear')
        or _authorized_any_obra(request, empresa_id, 'empleados.editar')
    ):
        return _response_error('Sin permiso para registrar charlas de cuadrilla.', 403)

    try:
        from datetime import timedelta
        from django.shortcuts import get_object_or_404
        payload = _payload(request) if request.body else {}
        trabajador_ids = payload.get('trabajador_ids') or []
        if not isinstance(trabajador_ids, list) or not trabajador_ids:
            return _response_error('Debes seleccionar al menos un trabajador asistente a la charla.')

        tema = (payload.get('tema') or 'Charla Operacional Diaria de 5 Minutos y AST').strip()[:220]
        relator = (payload.get('relator') or getattr(request.user, 'name', '') or request.user.username).strip()[:160]
        riesgos_criticos = (payload.get('riesgos_criticos') or '').strip()[:500]
        obra_id = payload.get('obra_id') or None
        tipo_cap_id = payload.get('tipo_capacitacion_id') or None
        fecha_realizacion = _parse_date(payload.get('fecha'), 'fecha') or timezone.localdate()

        with transaction.atomic():
            if tipo_cap_id:
                tipo_cap = get_object_or_404(TipoCapacitacion, pk=tipo_cap_id, empresa_id=empresa_id)
            else:
                tipo_cap, _ = TipoCapacitacion.objects.get_or_create(
                    empresa_id=empresa_id,
                    codigo='charla-5-min-ast',
                    defaults={
                        'nombre': 'Charla Operacional Diaria de 5 Minutos / AST (DS 44)',
                        'descripcion': 'Charla diaria de seguridad y Análisis Seguro de Trabajo en terreno antes de iniciar faena.',
                        'horas_sugeridas': 1,
                        'requiere_vencimiento': True,
                        'vigencia_meses': 12,
                        'activo': True,
                    },
                )

            workers = list(Trabajador.objects.filter(empresa_id=empresa_id, pk__in=trabajador_ids, activo=True))
            if not workers:
                return _response_error('Ninguno de los trabajadores seleccionados está activo en la empresa.')

            vencimiento = fecha_realizacion + timedelta(days=(tipo_cap.vigencia_meses or 12) * 30)
            obs_detalle = f"Tema: {tema}."
            if riesgos_criticos:
                obs_detalle += f" Riesgos/Controles AST: {riesgos_criticos}."

            registrados = 0
            for w in workers:
                CapacitacionTrabajador.objects.create(
                    empresa_id=empresa_id,
                    trabajador=w,
                    tipo_capacitacion=tipo_cap,
                    obra_id=obra_id,
                    fecha_realizacion=fecha_realizacion,
                    fecha_vencimiento=vencimiento,
                    relator=relator,
                    horas=1,
                    estado='vigente',
                    observaciones=obs_detalle,
                    registrado_por=request.user,
                )
                registrados += 1

            RegistroAuditoria.objects.create(
                empresa_id=empresa_id,
                actor=request.user,
                accion='prevencion.charla_cuadrilla.registrar',
                entidad='CapacitacionTrabajador',
                entidad_id=str(tipo_cap.pk),
                detalle={
                    'tema': tema,
                    'relator': relator,
                    'obra_id': str(obra_id) if obra_id else None,
                    'asistentes_count': registrados,
                    'fecha': fecha_realizacion.isoformat(),
                },
            )

        return JsonResponse({
            'registrados': registrados,
            'tema': tema,
            'fecha': fecha_realizacion.isoformat(),
        }, status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET', 'POST'])
def checklists_digitales_rf12(request, empresa_id):
    """RF-11 & RF-12: Registro y consulta de inspecciones y checklists digitales de terreno y equipos."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if request.method == 'GET':
        if not (
            _authorized_any_obra(request, empresa_id, 'documentos.ver')
            or _authorized_any_obra(request, empresa_id, 'equipos.ver')
            or _authorized_any_obra(request, empresa_id, 'obras.ver')
        ):
            return _response_error('Sin acceso.', 403)
        logs = (
            RegistroAuditoria.objects.filter(
                empresa_id=empresa_id,
                accion='prevencion.checklist.registrar',
            )
            .select_related('actor')
            .order_by('-creado_en')[:150]
        )
        obra_filter = request.GET.get('obra_id')
        results = []
        for entry in logs:
            det = entry.detalle if isinstance(entry.detalle, dict) else {}
            if obra_filter and str(det.get('obra_id') or '') != str(obra_filter):
                continue
            results.append({
                'id': str(entry.pk),
                'fecha': det.get('fecha') or entry.creado_en.date().isoformat(),
                'creado_en': entry.creado_en.isoformat(),
                'inspector': det.get('inspector') or (entry.actor.name if entry.actor else 'Supervisor'),
                'tipo_checklist': det.get('tipo_checklist', 'Inspección general'),
                'obra_id': det.get('obra_id'),
                'obra_nombre': det.get('obra_nombre', 'General empresa'),
                'equipo_id': det.get('equipo_id'),
                'equipo_nombre': det.get('equipo_nombre'),
                'resultado_global': det.get('resultado_global', 'conforme'),
                'items': det.get('items', []),
                'hallazgos': det.get('hallazgos', ''),
                'medidas_correctivas': det.get('medidas_correctivas', ''),
            })
        return JsonResponse({'results': results})

    try:
        data = _payload(request)
        obra_id = data.get('obra_id') or None
        if not (
            _authorized(request, empresa_id, 'documentos.crear', obra_id=obra_id)
            or _authorized(request, empresa_id, 'equipos.editar', obra_id=obra_id)
        ):
            return _response_error('Sin acceso para registrar inspecciones.', 403)
        tipo_checklist = str(data.get('tipo_checklist') or '').strip()
        if not tipo_checklist:
            return _response_error('El tipo de checklist es obligatorio.', 400)

        obra_nombre = 'Corporativo / Todas las obras'
        if obra_id:
            from apps.authorization.models import EmpresaObra
            eo = EmpresaObra.objects.select_related('obra').filter(empresa_id=empresa_id, obra_id=obra_id).first()
            if eo:
                obra_nombre = eo.obra.nombre

        equipo_id = data.get('equipo_id') or None
        equipo_nombre = None
        if equipo_id:
            eq = Equipo.objects.filter(pk=equipo_id, empresa_id=empresa_id).first()
            if eq:
                equipo_nombre = f"{eq.nombre} ({eq.codigo})"

        detalle = {
            'tipo_checklist': tipo_checklist[:160],
            'fecha': str(data.get('fecha') or timezone.localdate().isoformat())[:10],
            'obra_id': obra_id,
            'obra_nombre': obra_nombre,
            'equipo_id': str(equipo_id) if equipo_id else None,
            'equipo_nombre': equipo_nombre,
            'inspector': str(data.get('inspector') or getattr(request.user, 'name', '') or request.user.get_username())[:160],
            'resultado_global': str(data.get('resultado_global') or 'conforme')[:40],
            'items': data.get('items') if isinstance(data.get('items'), list) else [],
            'hallazgos': str(data.get('hallazgos') or '')[:2000],
            'medidas_correctivas': str(data.get('medidas_correctivas') or '')[:2000],
        }
        entry = RegistroAuditoria.objects.create(
            empresa_id=empresa_id,
            actor=request.user,
            accion='prevencion.checklist.registrar',
            entidad='ChecklistDigital',
            entidad_id=str(equipo_id or obra_id or empresa_id),
            detalle=detalle,
        )
        return JsonResponse({'id': str(entry.pk), **detalle}, status=201)
    except (ValueError, TypeError, ValidationError) as exc:
        return _response_error(str(exc))


@require_http_methods(['GET'])
def dossier_fiscalizacion_fuf_ds44(request, empresa_id):
    """RF-16: Estructura de evidencias según Formulario Único de Fiscalización (FUF) y DS 44."""
    if _unauthenticated(request):
        return _response_error('Autenticación requerida.', 401)
    if not (
        _authorized_any_obra(request, empresa_id, 'documentos.ver')
        or _authorized_any_obra(request, empresa_id, 'informes.ver')
    ):
        return _response_error('Sin acceso.', 403)

    obra_id = request.GET.get('obra_id') or None
    dash = calcular_dashboard_cumplimiento(empresa_id, obra_id=obra_id)
    comp_emp = dash['cumplimiento_empresa']
    kpis = dash['kpis']

    checklists_count = RegistroAuditoria.objects.filter(
        empresa_id=empresa_id, accion='prevencion.checklist.registrar'
    ).count()
    epp_total = EntregaEPP.objects.filter(empresa_id=empresa_id, firmado_recepcion=True).count()
    cap_total = CapacitacionTrabajador.objects.filter(empresa_id=empresa_id, estado='vigente').count()

    capitulos = [
        {
            'codigo': 'FUF-01',
            'norma': 'DS 44 Art. 22 y 47 / Ley 16.744',
            'titulo': 'Sistema de Gestión SST, Programa Preventivo y Matriz IPER',
            'descripcion': 'Existencia de Matriz de Identificación de Peligros y Evaluación de Riesgos (IPER), Programa Preventivo y Plan de Emergencia.',
            'evidencia': f"Cumplimiento corporativo: {comp_emp['porcentaje_cumplimiento']}% ({comp_emp['aprobados']}/{comp_emp['total_obligatorios']} requisitos aprobados).",
            'estado': 'cumple' if comp_emp['porcentaje_cumplimiento'] >= 80 else ('observado' if comp_emp['aprobados'] > 0 else 'pendiente'),
        },
        {
            'codigo': 'FUF-02',
            'norma': 'Código del Trabajo Art. 153 / DS 44',
            'titulo': 'Reglamento Interno de Orden, Higiene y Seguridad (RIOHS)',
            'descripcion': 'Ejemplar vigente del RIOHS en la empresa y constancias de recepción firmadas por los trabajadores.',
            'evidencia': f"Trabajadores evaluados con carpeta activa: {kpis['trabajadores_evaluados']} ({kpis['trabajadores_habilitados_doc']} con expediente al día).",
            'estado': 'cumple' if kpis['trabajadores_evaluados'] > 0 and kpis['porcentaje_cumplimiento_trabajadores'] >= 80 else 'observado',
        },
        {
            'codigo': 'FUF-03',
            'norma': 'DS 44 Art. 15 — Información de Riesgos Laborales (IRL / ODI)',
            'titulo': 'Inducción «Hombre Nuevo» e Información de Riesgos Laborales',
            'descripcion': 'Acreditación de que cada trabajador recibió información oportuna sobre los riesgos de su cargo y medidas preventivas.',
            'evidencia': f"Registros vigentes de capacitaciones e inducciones en plataforma: {cap_total} acreditaciones activas.",
            'estado': 'cumple' if cap_total > 0 and kpis['capacitaciones_pendientes'] == 0 else ('observado' if cap_total > 0 else 'pendiente'),
        },
        {
            'codigo': 'FUF-04',
            'norma': 'DS 44 / Procedimientos de Trabajo Seguro (PTS)',
            'titulo': 'Procedimientos de Trabajo Seguro (PTS) y Difusión Evaluada',
            'descripcion': 'Procedimientos escritos, aprobados y difundidos para tareas críticas (excavaciones, altura, izaje, herramientas eléctricas, hormigonado).',
            'evidencia': f"Catálogo de PTS y difusiones controladas por cargo ({cap_total} registros vigentes, {kpis['capacitaciones_pendientes']} pendientes).",
            'estado': 'cumple' if kpis['capacitaciones_pendientes'] == 0 and cap_total > 0 else 'observado',
        },
        {
            'codigo': 'FUF-05',
            'norma': 'DS 594 Art. 53 y 54 / DS 44',
            'titulo': 'Entrega, Certificación y Reposición de EPP',
            'descripcion': 'Provisión gratuita de Elementos de Protección Personal certificados y acordes al riesgo, con constancia de recepción.',
            'evidencia': f"{epp_total} entregas de EPP registradas con recepción firmada.",
            'estado': 'cumple' if epp_total > 0 else 'pendiente',
        },
        {
            'codigo': 'FUF-06',
            'norma': 'Ley 16.744 / Exámenes Ocupacionales Mutualidad',
            'titulo': 'Salud Ocupacional y Certificados de Aptitud Específica',
            'descripcion': 'Certificados de aptitud vigentes para trabajo en altura física, operadores de maquinaria y conductores (resguardando confidencialidad médica).',
            'evidencia': f"Documentos vencidos en trabajadores: {kpis['documentos_vencidos']} | Alertas activas: {kpis['alertas_no_leidas']}.",
            'estado': 'cumple' if kpis['documentos_vencidos'] == 0 and kpis['trabajadores_evaluados'] > 0 else 'observado',
        },
        {
            'codigo': 'FUF-07',
            'norma': 'DS 44 / Maquinaria, Equipos y Checklists Digitales',
            'titulo': 'Control de Equipos, Maquinaria Pesada e Inspecciones Pre-operacionales',
            'descripcion': 'Documentación técnica, mantenciones preventivas y listas de chequeo (checklists) digitales en terreno.',
            'evidencia': f"Equipos activos: {kpis['equipos_activos']} ({kpis['equipos_habilitados']} habilitados) | Checklists digitales registrados: {checklists_count}.",
            'estado': 'cumple' if kpis['equipos_con_vencidos'] == 0 and (kpis['equipos_activos'] > 0 or checklists_count > 0) else 'observado',
        },
        {
            'codigo': 'FUF-08',
            'norma': 'Protocolos MINSAL / SEREMI de Salud (PLANESI, PREXOR, RUVS, TMERT)',
            'titulo': 'Vigilancia Ambiental y de la Salud de Agentes de Riesgo (Sílice, Ruido, Radiación UV y Ergonomía)',
            'descripcion': 'Programas de vigilancia ocupacional para exposición a sílice (PLANESI), ruido (PREXOR), radiación UV solar (RUVS), trastornos musculoesqueléticos (TMERT) y ergonomía.',
            'evidencia': f"Cumplimiento corporativo SST/MINSAL: {comp_emp['porcentaje_cumplimiento']}% | Capacitaciones y protocolos vigentes: {cap_total}.",
            'estado': 'cumple' if comp_emp['porcentaje_cumplimiento'] >= 80 and cap_total > 0 else ('observado' if cap_total > 0 or comp_emp['aprobados'] > 0 else 'pendiente'),
        },
    ]

    return JsonResponse({
        'empresa_id': str(empresa_id),
        'obra_id': obra_id,
        'fecha_emision': dash['fecha_corte'],
        'kpis': kpis,
        'capitulos_fuf_ds44': capitulos,
    })



