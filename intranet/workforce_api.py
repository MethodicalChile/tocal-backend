"""API de trabajadores y cargos con aislamiento multiempresa explícito.

Las rutas empresariales exigen un permiso de ámbito empresa. Las rutas de obra
permiten permisos empresariales u otorgados específicamente para la obra.
No devuelve RUT salvo que exista empleados.ver_sensibles para ese ámbito.
"""
import json
from datetime import date
from functools import wraps
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from apps.authorization.models import Empresa, EmpresaObra, MembresiaEmpresa, RegistroAuditoria
from apps.authorization.permissions import authorized_obra_ids, has_any_obra_permission, has_permission
from .models import Cargo, Trabajador, AsignacionTrabajadorObra


PERFILES_CARGOS_TOCAL = [
    {
        "codigo": "gerente-general",
        "nombre": "Gerente General",
        "descripcion": "Dirección estratégica y representación general de la empresa constructora.",
    },
    {
        "codigo": "director-obras",
        "nombre": "Director de Obras",
        "descripcion": "Supervisión técnica, contractual y presupuestaria de las obras en ejecución.",
    },
    {
        "codigo": "residente-obras",
        "nombre": "Residente de Obras",
        "descripcion": "Responsable máximo de la ejecución técnica, administrativa y de seguridad en la obra.",
    },
    {
        "codigo": "administrador-obra",
        "nombre": "Administrador de Obra",
        "descripcion": "Planificación integral, control contractual, gestión de recursos y representación técnica en obra.",
    },
    {
        "codigo": "jefe-terreno",
        "nombre": "Jefe de Terreno",
        "descripcion": "Coordinación diaria de frentes de trabajo, cuadrillas, subcontratos y programación en terreno.",
    },
    {
        "codigo": "jefe-obras",
        "nombre": "Jefe de Obras",
        "descripcion": "Supervisión directa de partidas constructivas, capataces y cumplimiento de plazos en terreno.",
    },
    {
        "codigo": "oficina-tecnica",
        "nombre": "Encargado de Oficina Técnica",
        "descripcion": "Control de avance físico/financiero, estados de pago, adicionales, RDI y cubicaciones.",
    },
    {
        "codigo": "prevencionista-riesgos",
        "nombre": "Experto en Prevención de Riesgos",
        "descripcion": "Gestión de SSO, informes semanales PDR, charlas, capacitaciones, entrega de EPP y cumplimiento DS 44.",
    },
    {
        "codigo": "encargado-calidad",
        "nombre": "Encargado de Calidad",
        "descripcion": "Control de protocolos de calidad, ensayos de laboratorio, no conformidades y recepción de partidas.",
    },
    {
        "codigo": "administrativo-obras",
        "nombre": "Administrativo de Obras",
        "descripcion": "Control de asistencia, contratos, anexos, carpetas de personal, finiquitos y documentación laboral.",
    },
    {
        "codigo": "bodeguero",
        "nombre": "Bodeguero de Obra",
        "descripcion": "Recepción, almacenamiento, inventario y despacho de materiales, herramientas y EPP en obra.",
    },
    {
        "codigo": "topografo",
        "nombre": "Topógrafo",
        "descripcion": "Levantamientos topográficos, control geométrico, niveles y replanteo de precisión en obra.",
    },
    {
        "codigo": "trazador",
        "nombre": "Trazador",
        "descripcion": "Materialización de ejes, niveles y trazados constructivos en terreno conforme a planos de proyecto.",
    },
    {
        "codigo": "capataz",
        "nombre": "Capataz",
        "descripcion": "Liderazgo directo de cuadrillas operativas, distribución de tareas y control de seguridad en el frente.",
    },
    {
        "codigo": "maestro",
        "nombre": "Maestro",
        "descripcion": "Ejecución calificada de partidas de construcción civil, terminaciones, carpintería o albañilería.",
    },
    {
        "codigo": "maestro-primera",
        "nombre": "Maestro de Primera",
        "descripcion": "Ejecución especializada de partidas constructivas de alta precisión según planos y especificaciones.",
    },
    {
        "codigo": "maestro-segunda",
        "nombre": "Maestro de Segunda",
        "descripcion": "Ejecución de labores constructivas de especialidad intermedia en apoyo a partidas de obra.",
    },
    {
        "codigo": "jornal",
        "nombre": "Jornal",
        "descripcion": "Apoyo general de obra, orden y aseo, traslado de materiales y asistencia a cuadrillas.",
    },
    {
        "codigo": "operador-maquinaria",
        "nombre": "Operador de Maquinaria",
        "descripcion": "Operación segura y certificada de maquinaria pesada, equipos de izaje o movimiento de tierras.",
    },
    {
        "codigo": "conductor-obra",
        "nombre": "Conductor de Obra",
        "descripcion": "Conducción autorizada de vehículos de obra, transporte de materiales y logística operativa.",
    },
    {
        "codigo": "auxiliar-aseo",
        "nombre": "Auxiliar de Aseo",
        "descripcion": "Mantención de orden, higiene y sanitización de instalaciones de faena, oficinas y comedores.",
    },
]


def result(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def endpoint(methods):
    def decorate(func):
        @wraps(func)
        @require_http_methods(methods)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.is_active:
                return result({"error": "Sesión requerida"}, 401)
            try:
                return func(request, *args, **kwargs)
            except (ValidationError, ValueError) as error:
                if isinstance(error, ValidationError):
                    details = getattr(error, "message_dict", None) or error.messages
                else:
                    details = [str(error)]
                return result({"error": details}, 400)
            except IntegrityError:
                return result({"error": "Registro duplicado o incompatible"}, 409)
        return wrapped
    return decorate


def payload(request, allowed):
    if request.content_type.split(";")[0] != "application/json":
        raise ValidationError("Se requiere Content-Type: application/json")
    if len(request.body) > 100_000:
        raise ValidationError("Solicitud demasiado grande")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("JSON inválido")
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ValidationError("Campos inválidos o inesperados")
    return data


def company(company_id):
    try:
        UUID(str(company_id))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Identificador de empresa inválido")
    return get_object_or_404(Empresa, pk=company_id, activa=True)


def link(company_obj, obra_id):
    return get_object_or_404(EmpresaObra.objects.select_related("obra"), empresa=company_obj, obra_id=obra_id)


def permitted(request, empresa, action, obra=None):
    allowed = has_permission(user=request.user, permission=f"empleados.{action}",
                             empresa_id=empresa.pk, obra_id=obra.pk if obra else None)
    if not allowed:
        return result({"error": "No tienes permisos para esta operación"}, 403)
    return None


def worker_json(worker, sensitive=False):
    data = {"id": worker.pk, "empresa_id": str(worker.empresa_id),
            "nombres": worker.nombres, "apellido_paterno": worker.apellido_paterno,
            "apellido_materno": worker.apellido_materno, "activo": worker.activo,
            "usuario_id": str(worker.usuario_id) if worker.usuario_id else None,
            "usuario_email": worker.usuario.email if (worker.usuario_id and getattr(worker, "usuario", None)) else None,
            "usuario_nombre": (worker.usuario.name or worker.usuario.email) if (worker.usuario_id and getattr(worker, "usuario", None)) else None,
            "creado_en": worker.creado_en.isoformat()}
    if sensitive:
        data["rut"] = worker.rut
    return data


def role_json(cargo):
    return {"id": cargo.pk, "empresa_id": str(cargo.empresa_id), "codigo": cargo.codigo,
            "nombre": cargo.nombre, "descripcion": cargo.descripcion, "activo": cargo.activo}


def assignment_json(obj):
    data = {"id": obj.pk, "empresa_id": str(obj.empresa_id), "trabajador_id": obj.trabajador_id,
            "obra_id": obj.obra_id, "cargo_id": obj.cargo_id,
            "fecha_inicio": obj.fecha_inicio.isoformat(),
            "fecha_fin": obj.fecha_fin.isoformat() if obj.fecha_fin else None,
            "observaciones": obj.observaciones}
    if obj.trabajador_id:
        data["trabajador_nombre"] = " ".join(
            p for p in (obj.trabajador.nombres, obj.trabajador.apellido_paterno, obj.trabajador.apellido_materno) if p
        )
    if obj.cargo_id:
        data["cargo_nombre"] = obj.cargo.nombre
    if obj.obra_id:
        data["obra_nombre"] = obj.obra.nombre
    return data


def _audit(empresa, actor, accion, entidad, entidad_id, detalle=None):
    RegistroAuditoria.objects.create(
        empresa=empresa,
        actor=actor,
        accion=accion,
        entidad=entidad,
        entidad_id=str(entidad_id),
        detalle=detalle or {},
    )


def set_fields(instance, data, fields):
    for name in fields:
        if name in data:
            setattr(instance, name, data[name])
    instance.full_clean()
    instance.save()


@endpoint(["GET", "POST"])
def cargos(request, empresa_id):
    empresa = company(empresa_id)
    if request.method == "GET":
        if not has_any_obra_permission(user=request.user, permission="empleados.ver", empresa_id=empresa.pk):
            return result({"error": "No tienes permisos para esta operación"}, 403)
        return result({"results": [role_json(x) for x in Cargo.objects.filter(empresa=empresa)]})
    denied = permitted(request, empresa, "crear")
    if denied: return denied
    data = payload(request, {"codigo", "nombre", "descripcion", "activo"})
    if not data.get("codigo") or not data.get("nombre"):
        raise ValidationError("codigo y nombre son obligatorios")
    with transaction.atomic():
        obj = Cargo(empresa=empresa)
        set_fields(obj, data, ("codigo", "nombre", "descripcion", "activo"))
        _audit(empresa, request.user, "cargo.crear", "Cargo", obj.pk, {"codigo": obj.codigo})
    return result({"record": role_json(obj)}, 201)


@endpoint(["POST"])
def seed_tocal_cargos(request, empresa_id):
    empresa = company(empresa_id)
    denied = permitted(request, empresa, "crear")
    if denied:
        return denied
    creados = 0
    actualizados = 0
    with transaction.atomic():
        for item in PERFILES_CARGOS_TOCAL:
            cargo_obj, created = Cargo.objects.get_or_create(
                empresa=empresa,
                codigo=item["codigo"],
                defaults={
                    "nombre": item["nombre"],
                    "descripcion": item["descripcion"],
                    "activo": True,
                },
            )
            if created:
                creados += 1
            else:
                changed = False
                if not cargo_obj.descripcion and item["descripcion"]:
                    cargo_obj.descripcion = item["descripcion"]
                    changed = True
                if not cargo_obj.activo:
                    cargo_obj.activo = True
                    changed = True
                if changed:
                    cargo_obj.save(update_fields=["descripcion", "activo"])
                    actualizados += 1
        _audit(
            empresa,
            request.user,
            "cargo.catalogo_tocal",
            "Cargo",
            empresa.pk,
            {"creados": creados, "actualizados": actualizados},
        )
    all_cargos = Cargo.objects.filter(empresa=empresa).order_by("nombre")
    return result({
        "results": [role_json(x) for x in all_cargos],
        "creados": creados,
        "actualizados": actualizados,
    })


@endpoint(["GET", "PATCH"])
def cargo_detail(request, empresa_id, cargo_id):
    empresa = company(empresa_id)
    if request.method == "GET":
        if not has_any_obra_permission(user=request.user, permission="empleados.ver", empresa_id=empresa.pk):
            return result({"error": "No tienes permisos para esta operación"}, 403)
    else:
        denied = permitted(request, empresa, "editar")
        if denied: return denied
    obj = get_object_or_404(Cargo, empresa=empresa, pk=cargo_id)
    if request.method == "PATCH":
        data = payload(request, {"codigo", "nombre", "descripcion", "activo"})
        with transaction.atomic():
            set_fields(obj, data, ("codigo", "nombre", "descripcion", "activo"))
            _audit(empresa, request.user, "cargo.editar", "Cargo", obj.pk, {"campos": sorted(data.keys())})
    return result({"record": role_json(obj)})


@endpoint(["GET", "POST"])
def trabajadores(request, empresa_id):
    empresa = company(empresa_id)
    if request.method == "GET":
        scope = authorized_obra_ids(user=request.user, permission="empleados.ver", empresa_id=empresa.pk)
        if scope == set():
            return result({"error": "No tienes permisos para esta operación"}, 403)
        qs = Trabajador.objects.filter(empresa=empresa).select_related("usuario")
        obra_filter = request.GET.get("obra_id")
        if obra_filter:
            if scope is not None and obra_filter not in scope:
                return result({"error": "No tienes permisos para esta operación"}, 403)
            qs = qs.filter(asignaciones_obras__obra_id=obra_filter).distinct()
        elif scope is not None:
            qs = qs.filter(asignaciones_obras__obra_id__in=scope).distinct()

        activo_filter = request.GET.get("activo")
        if activo_filter in ("true", "1", "false", "0"):
            qs = qs.filter(activo=activo_filter in ("true", "1"))

        cargo_filter = request.GET.get("cargo_id")
        if cargo_filter:
            qs = qs.filter(asignaciones_obras__cargo_id=cargo_filter).distinct()

        q_filter = (request.GET.get("q") or "").strip()
        if q_filter:
            qs = qs.filter(
                models.Q(nombres__icontains=q_filter)
                | models.Q(apellido_paterno__icontains=q_filter)
                | models.Q(apellido_materno__icontains=q_filter)
            )

        sensitive = has_any_obra_permission(
            user=request.user,
            permission="empleados.ver_sensibles",
            empresa_id=empresa.pk,
            obra_ids=[obra_filter] if obra_filter else scope,
        )
        qs = qs.order_by("apellido_paterno", "nombres")
        total = qs.count()
        try:
            page = max(int(request.GET.get("page") or 1), 1)
            page_size = min(max(int(request.GET.get("page_size") or 250), 1), 250)
        except ValueError:
            page, page_size = 1, 250
        offset = (page - 1) * page_size
        items = qs[offset:offset + page_size]
        return result({
            "results": [worker_json(x, sensitive) for x in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    denied = permitted(request, empresa, "crear")
    if denied: return denied
    data = payload(request, {"nombres", "apellido_paterno", "apellido_materno", "rut", "usuario_id"})
    if not data.get("nombres") or not data.get("apellido_paterno"):
        raise ValidationError("nombres y apellido_paterno son obligatorios")
    if "rut" in data and permitted(request, empresa, "ver_sensibles") is not None:
        return result({"error": "No autorizado a registrar datos sensibles"}, 403)
    linked_user = None
    if data.get("usuario_id"):
        m = MembresiaEmpresa.objects.select_related("usuario").filter(
            empresa=empresa, usuario_id=data["usuario_id"], activa=True
        ).first()
        if not m:
            raise ValidationError("El usuario seleccionado no tiene membresía activa en esta empresa")
        if Trabajador.objects.filter(empresa=empresa, usuario=m.usuario).exists():
            raise ValidationError("Ese usuario ya está vinculado a otra ficha de trabajador en esta empresa")
        linked_user = m.usuario
    with transaction.atomic():
        obj = Trabajador(empresa=empresa, usuario=linked_user)
        set_fields(obj, data, ("nombres", "apellido_paterno", "apellido_materno", "rut"))
        _audit(empresa, request.user, "trabajador.crear", "Trabajador", obj.pk, {
            "con_rut": bool(data.get("rut")),
            "usuario_id": str(linked_user.pk) if linked_user else None,
        })
    return result({"record": worker_json(obj, permitted(request, empresa, "ver_sensibles") is None)}, 201)


@endpoint(["GET", "PATCH", "DELETE"])
def trabajador_detail(request, empresa_id, trabajador_id):
    empresa = company(empresa_id)
    action = "ver" if request.method == "GET" else ("desactivar" if request.method == "DELETE" else "editar")
    if request.method == "GET":
        scope = authorized_obra_ids(user=request.user, permission="empleados.ver", empresa_id=empresa.pk)
        if scope == set():
            return result({"error": "No tienes permisos para esta operación"}, 403)
    else:
        scope = None
        denied = permitted(request, empresa, action)
        if denied: return denied
    obj = get_object_or_404(Trabajador.objects.select_related("usuario"), empresa=empresa, pk=trabajador_id)
    if request.method == "GET" and scope is not None:
        if not AsignacionTrabajadorObra.objects.filter(empresa=empresa, trabajador=obj, obra_id__in=scope).exists():
            return result({"error": "No tienes permisos para esta operación"}, 403)
    sensitive = has_any_obra_permission(
        user=request.user,
        permission="empleados.ver_sensibles",
        empresa_id=empresa.pk,
        obra_ids=scope,
    )
    if request.method == "PATCH":
        data = payload(request, {"nombres", "apellido_paterno", "apellido_materno", "rut", "activo", "usuario_id"})
        if "rut" in data and not sensitive:
            return result({"error": "No autorizado a modificar datos sensibles"}, 403)
        if "usuario_id" in data:
            raw_uid = str(data.get("usuario_id") or "").strip()
            if not raw_uid:
                obj.usuario = None
            else:
                m = MembresiaEmpresa.objects.select_related("usuario").filter(
                    empresa=empresa, usuario_id=raw_uid, activa=True
                ).first()
                if not m:
                    raise ValidationError("El usuario seleccionado no tiene membresía activa en esta empresa")
                if Trabajador.objects.filter(empresa=empresa, usuario=m.usuario).exclude(pk=obj.pk).exists():
                    raise ValidationError("Ese usuario ya está vinculado a otra ficha de trabajador en esta empresa")
                obj.usuario = m.usuario
        with transaction.atomic():
            set_fields(obj, data, ("nombres", "apellido_paterno", "apellido_materno", "rut", "activo"))
            _audit(empresa, request.user, "trabajador.editar", "Trabajador", obj.pk, {"campos": sorted(set(data.keys()) - {"rut"})})
    if request.method == "DELETE":
        with transaction.atomic():
            if AsignacionTrabajadorObra.objects.filter(trabajador=obj, fecha_fin__isnull=True).exists():
                return result({"error": "Cierra las asignaciones vigentes antes de desactivar"}, 409)
            obj.activo = False
            obj.save(update_fields=["activo"])
            _audit(empresa, request.user, "trabajador.desactivar", "Trabajador", obj.pk, {})

    response = {"record": worker_json(obj, sensitive)}
    if request.method == "GET":
        linked_works = EmpresaObra.objects.filter(empresa=empresa).values("obra_id")
        history_qs = (
            AsignacionTrabajadorObra.objects
            .filter(empresa=empresa, trabajador=obj, obra_id__in=linked_works)
        )
        if scope is not None:
            history_qs = history_qs.filter(obra_id__in=scope)
        history = (
            history_qs
            .select_related("obra", "cargo", "trabajador")
            .order_by("-fecha_inicio", "-creado_en")
        )
        response["asignaciones"] = [
            {
                **assignment_json(item),
                "obra_nombre": item.obra.nombre,
                "cargo_nombre": item.cargo.nombre,
            }
            for item in history
        ]
    return result(response)


@endpoint(["GET", "POST"])
def asignaciones(request, empresa_id, obra_id):
    empresa = company(empresa_id)
    enlace = link(empresa, obra_id)

    # 1. Verificar permisos sobre la empresa y la obra
    accion = "ver" if request.method == "GET" else "editar"

    denied = permitted(
        request,
        empresa,
        accion,
        enlace.obra,
    )

    if denied:
        return denied

    # 2. Consultar asignaciones de la obra
    if request.method == "GET":
        qs = (
            AsignacionTrabajadorObra.objects
            .filter(
                empresa=empresa,
                obra=enlace.obra,
            )
            .select_related("trabajador", "cargo", "obra")
            .order_by("-fecha_inicio")[:250]
        )

        return result({
            "results": [assignment_json(x) for x in qs]
        })

    # 3. Validar datos recibidos
    data = payload(
        request,
        {
            "trabajador_id",
            "cargo_id",
            "fecha_inicio",
            "fecha_fin",
            "observaciones",
        },
    )

    for field in ("trabajador_id", "cargo_id", "fecha_inicio"):
        if not data.get(field):
            raise ValidationError(f"{field} es obligatorio")

    # 4. Validar que el trabajador pertenezca a la empresa
    worker = get_object_or_404(
        Trabajador,
        empresa=empresa,
        pk=data["trabajador_id"],
        activo=True,
    )

    # 5. Validar que el cargo pertenezca a la misma empresa
    cargo = get_object_or_404(
        Cargo,
        empresa=empresa,
        pk=data["cargo_id"],
        activo=True,
    )

    # 6. Validar fechas
    try:
        start = date.fromisoformat(data["fecha_inicio"])

        end = (
            date.fromisoformat(data["fecha_fin"])
            if data.get("fecha_fin")
            else None
        )

    except (TypeError, ValueError):
        raise ValidationError(
            "Las fechas deben utilizar YYYY-MM-DD"
        )

    if end is not None and end < start:
        raise ValidationError(
            "La fecha de término no puede ser anterior a la fecha de inicio"
        )

    # 7. Crear la asignación
    with transaction.atomic():
        obj = AsignacionTrabajadorObra(
            empresa=empresa,
            obra=enlace.obra,
            trabajador=worker,
            cargo=cargo,
            fecha_inicio=start,
            fecha_fin=end,
            observaciones=data.get("observaciones", ""),
        )

        obj.full_clean()
        obj.save()
        _audit(
            empresa,
            request.user,
            "asignacion_obra.crear",
            "AsignacionTrabajadorObra",
            obj.pk,
            {"obra_id": enlace.obra.pk, "trabajador_id": worker.pk, "cargo_id": cargo.pk},
        )

    return result({
        "record": assignment_json(obj)
    }, 201)

@endpoint(["PATCH"])
def asignacion_detail(request, empresa_id, obra_id, asignacion_id):
    empresa = company(empresa_id)
    enlace = link(empresa, obra_id)
    denied = permitted(request, empresa, "editar", enlace.obra)
    if denied: return denied
    obj = get_object_or_404(
        AsignacionTrabajadorObra.objects.select_related("trabajador", "cargo", "obra"),
        empresa=empresa, obra=enlace.obra, pk=asignacion_id,
    )
    data = payload(request, {"fecha_fin", "observaciones", "cargo_id", "fecha_cambio"})
    if "cargo_id" in data and data["cargo_id"] and str(data["cargo_id"]) != str(obj.cargo_id):
        nuevo_cargo = get_object_or_404(Cargo, empresa=empresa, pk=data["cargo_id"], activo=True)
        try:
            fecha_cambio = date.fromisoformat(data["fecha_cambio"]) if data.get("fecha_cambio") else date.today()
        except (TypeError, ValueError):
            raise ValidationError("fecha_cambio debe utilizar YYYY-MM-DD")
        if fecha_cambio < obj.fecha_inicio:
            raise ValidationError("La fecha de cambio de cargo no puede ser anterior al inicio de la asignación")
        with transaction.atomic():
            obj.fecha_fin = fecha_cambio
            if "observaciones" in data:
                obj.observaciones = data["observaciones"]
            obj.full_clean()
            obj.save()
            nueva = AsignacionTrabajadorObra(
                empresa=empresa,
                obra=enlace.obra,
                trabajador=obj.trabajador,
                cargo=nuevo_cargo,
                fecha_inicio=fecha_cambio,
                fecha_fin=None,
                observaciones=data.get("observaciones", ""),
            )
            nueva.full_clean()
            nueva.save()
            _audit(
                empresa,
                request.user,
                "asignacion_obra.cambio_cargo",
                "AsignacionTrabajadorObra",
                nueva.pk,
                {
                    "obra_id": enlace.obra.pk,
                    "asignacion_anterior_id": obj.pk,
                    "cargo_anterior_id": obj.cargo_id,
                    "cargo_nuevo_id": nuevo_cargo.pk,
                    "fecha_cambio": fecha_cambio.isoformat(),
                },
            )
        return result({
            "record": assignment_json(nueva),
            "asignacion_anterior": assignment_json(obj),
        })

    if "fecha_fin" in data:
        try:
            obj.fecha_fin = date.fromisoformat(data["fecha_fin"]) if data["fecha_fin"] else None
        except (TypeError, ValueError):
            raise ValidationError("fecha_fin debe utilizar YYYY-MM-DD")
    if "observaciones" in data:
        obj.observaciones = data["observaciones"]
    with transaction.atomic():
        obj.full_clean()
        obj.save()
        _audit(
            empresa,
            request.user,
            "asignacion_obra.editar",
            "AsignacionTrabajadorObra",
            obj.pk,
            {"obra_id": enlace.obra.pk, "campos": sorted(data.keys())},
        )
    return result({"record": assignment_json(obj)})


@endpoint(["POST"])
def trabajadores_carga_masiva(request, empresa_id):
    """Carga masiva rápida de cuadrillas / trabajadores desde líneas CSV o planilla pegada."""
    empresa = company(empresa_id)
    denied = permitted(request, empresa, "crear")
    if denied:
        return denied

    data = payload(request, {"lineas_texto", "obra_id", "cargo_id"})
    raw_text = str(data.get("lineas_texto") or "").strip()
    if not raw_text:
        raise ValidationError("Debes ingresar al menos una fila con datos de trabajadores.")

    default_obra_id = str(data.get("obra_id") or "").strip()
    default_cargo_id = str(data.get("cargo_id") or "").strip()

    enlace_default = link(empresa, default_obra_id) if default_obra_id else None
    cargo_default = (
        get_object_or_404(Cargo, empresa=empresa, pk=default_cargo_id, activo=True)
        if default_cargo_id
        else None
    )

    sens = has_any_obra_permission(
        user=request.user,
        permission="empleados.ver_sensibles",
        empresa_id=empresa.pk,
    )
    hoy = date.today()
    creados = 0
    actualizados = 0
    asignaciones_creadas = 0
    errores = []
    registros = []

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    with transaction.atomic():
        for idx, line in enumerate(lines, start=1):
            # Ignorar cabecera si la primera línea dice "nombres" o "rut"
            lower = line.lower()
            if idx == 1 and ("apellido" in lower or ("nombre" in lower and "rut" in lower)):
                continue
            sep = ";" if ";" in line else ("\t" if "\t" in line else ",")
            parts = [p.strip() for p in line.split(sep)]
            if len(parts) < 2:
                errores.append(f"Línea {idx}: formato inválido (se requiere al menos Nombres y Apellido Paterno).")
                continue

            nombres = parts[0][:120]
            ap_paterno = parts[1][:120]
            ap_materno = parts[2][:120] if len(parts) >= 3 else ""
            rut_val = parts[3][:20] if (len(parts) >= 4 and sens) else None
            if rut_val == "":
                rut_val = None

            if not nombres or not ap_paterno:
                errores.append(f"Línea {idx}: Nombres y Apellido Paterno son obligatorios.")
                continue

            worker = None
            if rut_val:
                worker = Trabajador.objects.filter(empresa=empresa, rut__iexact=rut_val).first()

            if worker:
                worker.nombres = nombres
                worker.apellido_paterno = ap_paterno
                if ap_materno:
                    worker.apellido_materno = ap_materno
                worker.activo = True
                worker.full_clean()
                worker.save()
                actualizados += 1
            else:
                worker = Trabajador(
                    empresa=empresa,
                    nombres=nombres,
                    apellido_paterno=ap_paterno,
                    apellido_materno=ap_materno,
                    rut=rut_val,
                    activo=True,
                )
                worker.full_clean()
                worker.save()
                creados += 1

            if enlace_default and cargo_default:
                existe_asig = AsignacionTrabajadorObra.objects.filter(
                    empresa=empresa,
                    obra=enlace_default.obra,
                    trabajador=worker,
                    fecha_fin__isnull=True,
                ).exists()
                if not existe_asig:
                    asig = AsignacionTrabajadorObra(
                        empresa=empresa,
                        obra=enlace_default.obra,
                        trabajador=worker,
                        cargo=cargo_default,
                        fecha_inicio=hoy,
                        observaciones="Asignación creada por carga masiva de cuadrilla",
                    )
                    asig.full_clean()
                    asig.save()
                    asignaciones_creadas += 1

            registros.append(worker_json(worker, sens))

        _audit(
            empresa,
            request.user,
            "trabajador.carga_masiva",
            "Trabajador",
            empresa.pk,
            {
                "creados": creados,
                "actualizados": actualizados,
                "asignaciones_creadas": asignaciones_creadas,
                "errores": len(errores),
            },
        )

    return result({
        "creados": creados,
        "actualizados": actualizados,
        "asignaciones_creadas": asignaciones_creadas,
        "errores": errores,
        "results": registros,
    }, 201)

