"""Servicios de cálculo de cumplimiento documental y alertas de vencimiento (Etapas 4, 5 y 6)."""
from datetime import date
from django.db import models, transaction
from django.utils import timezone

from apps.authorization.models import Empresa, EmpresaObra, RegistroAuditoria
from intranet.models import AsignacionTrabajadorObra, ChecklistEvaluacion, Trabajador
from .models import (
    AlertaVencimiento,
    ArchivoDocumentoEmpresa,
    ArchivoDocumentoEquipo,
    ArchivoDocumentoTrabajador,
    AsignacionEquipoObra,
    CapacitacionTrabajador,
    CategoriaEPP,
    ConfiguracionAlertaEmpresa,
    DocumentoEmpresa,
    DocumentoEquipo,
    DocumentoTrabajador,
    EntregaEPP,
    Equipo,
    RequisitoCapacitacion,
    RequisitoDocumental,
    TipoCapacitacion,
    TipoDocumento,
)


ESTADOS_CUMPLIMIENTO = {
    "aprobado": "Aprobado",
    "pendiente": "Pendiente de revisión",
    "rechazado": "Rechazado",
    "vencido": "Vencido",
    "faltante": "Faltante",
    "no_aplicable": "No aplicable",
}


def calcular_vencimiento_info(fecha_vencimiento, hoy=None, dias_umbral=30):
    """Calcula días restantes y estado de vencimiento de una fecha."""
    if not fecha_vencimiento:
        return {
            "vencido": False,
            "por_vencer": False,
            "dias_restantes": None,
            "estado_vencimiento": "sin_vencimiento",
        }
    hoy = hoy or timezone.localdate()
    dias = (fecha_vencimiento - hoy).days
    if dias < 0:
        estado = "vencido"
    elif dias <= dias_umbral:
        estado = "por_vencer"
    else:
        estado = "vigente"
    return {
        "vencido": dias < 0,
        "por_vencer": 0 <= dias <= dias_umbral,
        "dias_restantes": dias,
        "estado_vencimiento": estado,
    }


def estado_documento_efectivo(doc, hoy=None, ids_con_archivo=None):
    """Determina el estado efectivo de un DocumentoTrabajador exigiendo evidencia para aprobado."""
    hoy = hoy or timezone.localdate()
    if doc.fecha_vencimiento and doc.fecha_vencimiento < hoy:
        return "vencido"
    if doc.estado == "rechazado":
        return "rechazado"
    tiene_archivo = (
        (doc.pk in ids_con_archivo)
        if ids_con_archivo is not None
        else (getattr(doc, "version_aprobada_id", None) is not None or doc.archivos.exists())
    )
    if doc.estado == "aprobado" and tiene_archivo:
        return "aprobado"
    return "pendiente"


def calcular_cumplimiento_trabajador(empresa_id, trabajador_id, obra_id=None, hoy=None):
    """Calcula en el backend el cumplimiento documental de un trabajador por cargo y obra."""
    hoy = hoy or timezone.localdate()

    asignaciones_qs = (
        AsignacionTrabajadorObra.objects.filter(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id,
            fecha_inicio__lte=hoy,
        )
        .filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy))
        .select_related("obra", "cargo")
        .order_by("obra__nombre")
    )
    if obra_id:
        asignaciones_qs = asignaciones_qs.filter(obra_id=obra_id)
    asignaciones = list(asignaciones_qs)

    reglas = list(
        RequisitoDocumental.objects.filter(
            empresa_id=empresa_id,
            activo=True,
            tipo_documento__activo=True,
            tipo_documento__categoria="trabajador",
        ).select_related("tipo_documento", "cargo", "obra")
    )

    documentos = list(
        DocumentoTrabajador.objects.filter(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id,
        )
        .select_related("tipo_documento", "obra", "revisado_por")
        .order_by("-creado_en")
    )
    ids_con_archivo = set(
        ArchivoDocumentoTrabajador.objects.filter(
            documento__empresa_id=empresa_id,
            documento__trabajador_id=trabajador_id,
        ).values_list("documento_id", flat=True)
    )

    requisitos_evaluados = []
    por_obra = []

    for asig in asignaciones:
        # Combinar reglas generales y específicas sin duplicar tipo_documento por obra
        reglas_aplicables = {}
        for req in reglas:
            if req.cargo_id and str(req.cargo_id) != str(asig.cargo_id):
                continue
            if req.obra_id and str(req.obra_id) != str(asig.obra_id):
                continue
            tid = str(req.tipo_documento_id)
            prev = reglas_aplicables.get(tid)
            origen = (
                "cargo_y_obra"
                if (req.cargo_id and req.obra_id)
                else ("obra" if req.obra_id else ("cargo" if req.cargo_id else "empresa"))
            )
            if prev is None:
                reglas_aplicables[tid] = {
                    "requisito_id": str(req.pk),
                    "tipo_documento": req.tipo_documento,
                    "obligatorio": req.obligatorio,
                    "origen": origen,
                }
            else:
                prev["obligatorio"] = prev["obligatorio"] or req.obligatorio
                if origen in ("cargo_y_obra", "obra"):
                    prev["origen"] = origen

        items_obra = []
        for tid, info_req in sorted(
            reglas_aplicables.items(), key=lambda x: x[1]["tipo_documento"].nombre
        ):
            tipo = info_req["tipo_documento"]
            candidatos = [
                d
                for d in documentos
                if str(d.tipo_documento_id) == tid
                and (d.obra_id is None or str(d.obra_id) == str(asig.obra_id))
            ]
            estados_cand = [
                (d, estado_documento_efectivo(d, hoy=hoy, ids_con_archivo=ids_con_archivo))
                for d in candidatos
            ]
            doc_elegido = None
            if any(est == "aprobado" for _, est in estados_cand):
                estado = "aprobado"
                doc_elegido = next(d for d, est in estados_cand if est == "aprobado")
            elif any(est == "vencido" for _, est in estados_cand):
                estado = "vencido"
                doc_elegido = next(d for d, est in estados_cand if est == "vencido")
            elif any(est == "rechazado" for _, est in estados_cand):
                estado = "rechazado"
                doc_elegido = next(d for d, est in estados_cand if est == "rechazado")
            elif estados_cand:
                estado = "pendiente"
                doc_elegido = estados_cand[0][0]
            else:
                estado = "faltante"

            venc_info = calcular_vencimiento_info(
                doc_elegido.fecha_vencimiento if doc_elegido else None, hoy=hoy
            )
            item_eval = {
                "key": f"{tid}:{asig.obra_id}",
                "requisito_id": info_req["requisito_id"],
                "tipo_documento_id": tid,
                "tipo_documento_codigo": tipo.codigo,
                "tipo_documento_nombre": tipo.nombre,
                "requiere_vencimiento": tipo.requiere_vencimiento,
                "obra_id": str(asig.obra_id),
                "obra_nombre": asig.obra.nombre,
                "cargo_id": str(asig.cargo_id),
                "cargo_nombre": asig.cargo.nombre,
                "obligatorio": info_req["obligatorio"],
                "origen": info_req["origen"],
                "estado": estado,
                "estado_label": ESTADOS_CUMPLIMIENTO[estado],
                "documento_id": str(doc_elegido.pk) if doc_elegido else None,
                "fecha_vencimiento": (
                    doc_elegido.fecha_vencimiento.isoformat()
                    if (doc_elegido and doc_elegido.fecha_vencimiento)
                    else None
                ),
                "dias_restantes": venc_info["dias_restantes"],
                "por_vencer": venc_info["por_vencer"],
            }
            items_obra.append(item_eval)
            requisitos_evaluados.append(item_eval)

        oblig_obra = [i for i in items_obra if i["obligatorio"]]
        total_ob = len(oblig_obra)
        aprob_ob = sum(1 for i in oblig_obra if i["estado"] == "aprobado")
        pend_ob = sum(1 for i in oblig_obra if i["estado"] == "pendiente")
        rech_ob = sum(1 for i in oblig_obra if i["estado"] == "rechazado")
        venc_ob = sum(1 for i in oblig_obra if i["estado"] == "vencido")
        falt_ob = sum(1 for i in oblig_obra if i["estado"] == "faltante")
        pct_ob = round((aprob_ob / total_ob) * 100, 1) if total_ob > 0 else 100.0
        por_obra.append(
            {
                "obra_id": str(asig.obra_id),
                "obra_nombre": asig.obra.nombre,
                "cargo_id": str(asig.cargo_id),
                "cargo_nombre": asig.cargo.nombre,
                "total_obligatorios": total_ob,
                "aprobados": aprob_ob,
                "pendientes": pend_ob,
                "rechazados": rech_ob,
                "vencidos": venc_ob,
                "faltantes": falt_ob,
                "porcentaje_cumplimiento": pct_ob,
                "habilitado_documentalmente": aprob_ob == total_ob,
                "requisitos": items_obra,
            }
        )

    obligatorios = [i for i in requisitos_evaluados if i["obligatorio"]]
    total_obligatorios = len(obligatorios)
    aprobados = sum(1 for i in obligatorios if i["estado"] == "aprobado")
    pendientes = sum(1 for i in obligatorios if i["estado"] == "pendiente")
    rechazados = sum(1 for i in obligatorios if i["estado"] == "rechazado")
    vencidos = sum(1 for i in obligatorios if i["estado"] == "vencido")
    faltantes = sum(1 for i in obligatorios if i["estado"] == "faltante")

    if not asignaciones:
        porcentaje = 0.0
        habilitado = False
        estado_cumplimiento = "sin_asignacion"
        estado_cumplimiento_label = "Sin asignación activa"
    elif total_obligatorios == 0:
        porcentaje = 100.0
        habilitado = True
        estado_cumplimiento = "sin_requisitos_configurados"
        estado_cumplimiento_label = "Sin requisitos configurados"
    else:
        porcentaje = round((aprobados / total_obligatorios) * 100, 1)
        habilitado = aprobados == total_obligatorios
        estado_cumplimiento = "al_dia" if habilitado else "incumplimiento"
        estado_cumplimiento_label = "Al día" if habilitado else "Con pendientes o incumplimiento"

    return {
        "trabajador_id": str(trabajador_id),
        "empresa_id": str(empresa_id),
        "fecha_evaluacion": hoy.isoformat(),
        "asignaciones_vigentes": len(asignaciones),
        "total_obligatorios": total_obligatorios,
        "aprobados": aprobados,
        "pendientes": pendientes,
        "rechazados": rechazados,
        "vencidos": vencidos,
        "faltantes": faltantes,
        "porcentaje_cumplimiento": porcentaje,
        "habilitado_documentalmente": habilitado,
        "estado_cumplimiento": estado_cumplimiento,
        "estado_cumplimiento_label": estado_cumplimiento_label,
        "por_obra": por_obra,
        "requisitos": requisitos_evaluados,
    }


def obtener_configuracion_alertas(empresa_id):
    """Obtiene o crea la configuración de alertas por defecto para una empresa."""
    config, _ = ConfiguracionAlertaEmpresa.objects.get_or_create(empresa_id=empresa_id)
    return config


def sincronizar_alertas_vencimiento(empresa_id=None, hoy=None, actor=None):
    """Detecta documentos vencidos o próximos a vencer y registra alertas sin duplicados."""
    hoy = hoy or timezone.localdate()
    empresas_qs = Empresa.objects.filter(activa=True)
    if empresa_id:
        empresas_qs = empresas_qs.filter(pk=empresa_id)

    creadas = 0
    actualizadas = 0

    for empresa in empresas_qs:
        config = obtener_configuracion_alertas(empresa.pk)
        if not config.activo:
            continue
        umbrales = sorted(
            {int(x) for x in (config.dias_anticipacion or [60, 30, 15, 7]) if isinstance(x, int) and x > 0}
        )
        max_umbral = max(umbrales) if umbrales else 30

        docs_trab = (
            DocumentoTrabajador.objects.filter(
                empresa=empresa,
                fecha_vencimiento__isnull=False,
                trabajador__activo=True,
            )
            .exclude(estado="rechazado")
            .select_related("trabajador", "tipo_documento", "obra")
        )

        def _registrar_alerta(entidad_tipo, entidad_id, doc, titulo, obra=None):
            nonlocal creadas, actualizadas
            dias = (doc.fecha_vencimiento - hoy).days
            if dias < 0:
                if not config.notificar_vencidos:
                    return
                nivel = "vencido"
                umbral = 0
            elif dias <= max_umbral:
                nivel = "por_vencer"
                aplicables = [u for u in umbrales if dias <= u]
                umbral = min(aplicables) if aplicables else max_umbral
            else:
                return

            with transaction.atomic():
                alerta, created = AlertaVencimiento.objects.update_or_create(
                    empresa=empresa,
                    entidad_tipo=entidad_tipo,
                    documento_id=str(doc.pk),
                    nivel=nivel,
                    umbral_dias=umbral,
                    fecha_vencimiento=doc.fecha_vencimiento,
                    defaults={
                        "obra": obra,
                        "entidad_id": str(entidad_id),
                        "titulo": titulo[:240],
                        "dias_restantes": dias,
                    },
                )
                if created:
                    creadas += 1
                    RegistroAuditoria.objects.create(
                        empresa=empresa,
                        actor=actor,
                        accion="alertas.vencimiento.generar",
                        entidad="AlertaVencimiento",
                        entidad_id=str(alerta.pk),
                        detalle={
                            "entidad_tipo": entidad_tipo,
                            "documento_id": str(doc.pk),
                            "nivel": nivel,
                            "umbral_dias": umbral,
                            "dias_restantes": dias,
                        },
                    )
                else:
                    actualizadas += 1

        for doc in docs_trab:
            nombre_trab = f"{doc.trabajador.nombres} {doc.trabajador.apellido_paterno}".strip()
            _registrar_alerta("trabajador", doc.trabajador_id, doc, f"{doc.tipo_documento.nombre} — {nombre_trab}", doc.obra)

        docs_emp = (
            DocumentoEmpresa.objects.filter(
                empresa=empresa,
                fecha_vencimiento__isnull=False,
            )
            .exclude(estado="rechazado")
            .select_related("tipo_documento", "obra")
        )
        for doc in docs_emp:
            sufijo = doc.obra.nombre if doc.obra else empresa.nombre
            _registrar_alerta("empresa", empresa.pk, doc, f"{doc.tipo_documento.nombre} — {sufijo}", doc.obra)

        docs_eq = (
            DocumentoEquipo.objects.filter(
                empresa=empresa,
                fecha_vencimiento__isnull=False,
                equipo__activo=True,
            )
            .exclude(estado="rechazado")
            .select_related("equipo", "tipo_documento", "obra")
        )
        for doc in docs_eq:
            _registrar_alerta("equipo", doc.equipo_id, doc, f"{doc.tipo_documento.nombre} — {doc.equipo.nombre}", doc.obra)

    return {"creadas": creadas, "actualizadas": actualizadas, "fecha": hoy.isoformat()}


def calcular_cumplimiento_empresa(empresa_id, obra_id=None, hoy=None):
    """Calcula el cumplimiento documental corporativo de la empresa y/u obra."""
    hoy = hoy or timezone.localdate()
    reglas_qs = RequisitoDocumental.objects.filter(
        empresa_id=empresa_id,
        activo=True,
        tipo_documento__activo=True,
        tipo_documento__categoria="empresa",
    ).select_related("tipo_documento", "obra")
    if obra_id:
        reglas_qs = reglas_qs.filter(models.Q(obra__isnull=True) | models.Q(obra_id=obra_id))
    else:
        reglas_qs = reglas_qs.filter(obra__isnull=True)

    docs_qs = DocumentoEmpresa.objects.filter(empresa_id=empresa_id).select_related("tipo_documento", "obra")
    if obra_id:
        docs_qs = docs_qs.filter(models.Q(obra__isnull=True) | models.Q(obra_id=obra_id))
    documentos = list(docs_qs)
    ids_con_archivo = set(
        ArchivoDocumentoEmpresa.objects.filter(documento__empresa_id=empresa_id).values_list("documento_id", flat=True)
    )

    items = []
    seen = set()
    for req in reglas_qs:
        tid = str(req.tipo_documento_id)
        if tid in seen:
            continue
        seen.add(tid)
        candidatos = [d for d in documentos if str(d.tipo_documento_id) == tid]
        estados = [(d, estado_documento_efectivo(d, hoy=hoy, ids_con_archivo=ids_con_archivo)) for d in candidatos]
        doc_elegido = None
        if any(e == "aprobado" for _, e in estados):
            estado = "aprobado"
            doc_elegido = next(d for d, e in estados if e == "aprobado")
        elif any(e == "vencido" for _, e in estados):
            estado = "vencido"
            doc_elegido = next(d for d, e in estados if e == "vencido")
        elif any(e == "rechazado" for _, e in estados):
            estado = "rechazado"
            doc_elegido = next(d for d, e in estados if e == "rechazado")
        elif estados:
            estado = "pendiente"
            doc_elegido = estados[0][0]
        else:
            estado = "faltante"
        items.append({
            "requisito_id": str(req.pk),
            "tipo_documento_id": tid,
            "tipo_documento_nombre": req.tipo_documento.nombre,
            "obligatorio": req.obligatorio,
            "estado": estado,
            "estado_label": ESTADOS_CUMPLIMIENTO[estado],
            "documento_id": str(doc_elegido.pk) if doc_elegido else None,
            "fecha_vencimiento": doc_elegido.fecha_vencimiento.isoformat() if (doc_elegido and doc_elegido.fecha_vencimiento) else None,
        })

    oblig = [i for i in items if i["obligatorio"]]
    total_ob = len(oblig)
    aprob = sum(1 for i in oblig if i["estado"] == "aprobado")
    pend = sum(1 for i in oblig if i["estado"] == "pendiente")
    rech = sum(1 for i in oblig if i["estado"] == "rechazado")
    venc = sum(1 for i in oblig if i["estado"] == "vencido")
    falt = sum(1 for i in oblig if i["estado"] == "faltante")
    pct = round((aprob / total_ob) * 100, 1) if total_ob > 0 else 100.0
    estado_global = "al_dia" if aprob == total_ob else "incumplimiento"
    return {
        "empresa_id": str(empresa_id),
        "obra_id": str(obra_id) if obra_id else None,
        "total_obligatorios": total_ob,
        "aprobados": aprob,
        "pendientes": pend,
        "rechazados": rech,
        "vencidos": venc,
        "faltantes": falt,
        "porcentaje_cumplimiento": pct,
        "habilitada": aprob == total_ob,
        "estado_global": estado_global,
        "resumen": {
            "total_obligatorios": total_ob,
            "aprobados": aprob,
            "pendientes": pend,
            "rechazados": rech,
            "vencidos": venc,
            "faltantes": falt,
        },
        "requisitos": items,
    }


def calcular_cumplimiento_equipo(empresa_id, equipo_id, obra_id=None, hoy=None):
    """Calcula el cumplimiento documental de un equipo/maquinaria (T8.4)."""
    hoy = hoy or timezone.localdate()
    reglas_qs = RequisitoDocumental.objects.filter(
        empresa_id=empresa_id,
        activo=True,
        tipo_documento__activo=True,
        tipo_documento__categoria="equipo",
    ).select_related("tipo_documento", "obra")
    if obra_id:
        reglas_qs = reglas_qs.filter(models.Q(obra__isnull=True) | models.Q(obra_id=obra_id))

    documentos = list(
        DocumentoEquipo.objects.filter(empresa_id=empresa_id, equipo_id=equipo_id).select_related("tipo_documento", "obra")
    )
    ids_con_archivo = set(
        ArchivoDocumentoEquipo.objects.filter(documento__empresa_id=empresa_id, documento__equipo_id=equipo_id).values_list("documento_id", flat=True)
    )

    items = []
    seen = set()
    for req in reglas_qs:
        tid = str(req.tipo_documento_id)
        if tid in seen:
            continue
        seen.add(tid)
        candidatos = [
            d for d in documentos
            if str(d.tipo_documento_id) == tid and (obra_id is None or d.obra_id is None or str(d.obra_id) == str(obra_id))
        ]
        estados = [(d, estado_documento_efectivo(d, hoy=hoy, ids_con_archivo=ids_con_archivo)) for d in candidatos]
        doc_elegido = None
        if any(e == "aprobado" for _, e in estados):
            estado = "aprobado"
            doc_elegido = next(d for d, e in estados if e == "aprobado")
        elif any(e == "vencido" for _, e in estados):
            estado = "vencido"
            doc_elegido = next(d for d, e in estados if e == "vencido")
        elif any(e == "rechazado" for _, e in estados):
            estado = "rechazado"
            doc_elegido = next(d for d, e in estados if e == "rechazado")
        elif estados:
            estado = "pendiente"
            doc_elegido = estados[0][0]
        else:
            estado = "faltante"
        items.append({
            "requisito_id": str(req.pk),
            "tipo_documento_id": tid,
            "tipo_documento_nombre": req.tipo_documento.nombre,
            "obligatorio": req.obligatorio,
            "estado": estado,
            "estado_label": ESTADOS_CUMPLIMIENTO[estado],
            "documento_id": str(doc_elegido.pk) if doc_elegido else None,
            "fecha_vencimiento": doc_elegido.fecha_vencimiento.isoformat() if (doc_elegido and doc_elegido.fecha_vencimiento) else None,
        })

    oblig = [i for i in items if i["obligatorio"]]
    total_ob = len(oblig)
    aprob = sum(1 for i in oblig if i["estado"] == "aprobado")
    pend = sum(1 for i in oblig if i["estado"] == "pendiente")
    rech = sum(1 for i in oblig if i["estado"] == "rechazado")
    venc = sum(1 for i in oblig if i["estado"] == "vencido")
    falt = sum(1 for i in oblig if i["estado"] == "faltante")
    pct = round((aprob / total_ob) * 100, 1) if total_ob > 0 else 100.0
    estado_global = "al_dia" if aprob == total_ob else "incumplimiento"
    return {
        "equipo_id": str(equipo_id),
        "empresa_id": str(empresa_id),
        "total_obligatorios": total_ob,
        "aprobados": aprob,
        "pendientes": pend,
        "rechazados": rech,
        "vencidos": venc,
        "faltantes": falt,
        "porcentaje_cumplimiento": pct,
        "habilitado_operacion": aprob == total_ob,
        "estado_global": estado_global,
        "resumen": {
            "total_obligatorios": total_ob,
            "aprobados": aprob,
            "pendientes": pend,
            "rechazados": rech,
            "vencidos": venc,
            "faltantes": falt,
        },
        "requisitos": items,
    }


def calcular_habilitacion_preventiva(empresa_id, trabajador_id, obra_id=None, hoy=None):
    """Evalúa habilitación preventiva combinando documentos, capacitaciones y EPP (T9.4).
    No bloquea asignaciones laborales automáticamente; expone estado informativo.
    """
    hoy = hoy or timezone.localdate()
    doc_comp = calcular_cumplimiento_trabajador(empresa_id, trabajador_id, obra_id=obra_id, hoy=hoy)

    asignaciones_qs = (
        AsignacionTrabajadorObra.objects.filter(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id,
            fecha_inicio__lte=hoy,
        )
        .filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy))
    )
    if obra_id:
        asignaciones_qs = asignaciones_qs.filter(obra_id=obra_id)
    asignaciones = list(asignaciones_qs)
    cargo_ids = {a.cargo_id for a in asignaciones if a.cargo_id}
    obra_ids = {a.obra_id for a in asignaciones if a.obra_id}

    req_cap_qs = RequisitoCapacitacion.objects.filter(
        empresa_id=empresa_id,
        activo=True,
        tipo_capacitacion__activo=True,
    ).select_related("tipo_capacitacion")
    requisitos_cap = [
        r for r in req_cap_qs
        if (r.cargo_id is None or r.cargo_id in cargo_ids)
        and (r.obra_id is None or r.obra_id in obra_ids or (obra_id and str(r.obra_id) == str(obra_id)))
    ]

    capacitaciones = list(
        CapacitacionTrabajador.objects.filter(
            empresa_id=empresa_id,
            trabajador_id=trabajador_id,
        ).select_related("tipo_capacitacion")
    )

    cap_evaluadas = []
    seen_cap = set()
    for req in requisitos_cap:
        cid = str(req.tipo_capacitacion_id)
        if cid in seen_cap:
            continue
        seen_cap.add(cid)
        regs = [c for c in capacitaciones if str(c.tipo_capacitacion_id) == cid]
        vigente = any(
            c.estado == "vigente" and (not c.fecha_vencimiento or c.fecha_vencimiento >= hoy)
            for c in regs
        )
        vencida = any(
            c.estado == "vencida" or (c.fecha_vencimiento and c.fecha_vencimiento < hoy)
            for c in regs
        )
        estado_cap = "vigente" if vigente else ("vencida" if vencida else "faltante")
        cap_evaluadas.append({
            "tipo_capacitacion_id": cid,
            "nombre": req.tipo_capacitacion.nombre,
            "obligatorio": req.obligatorio,
            "estado": estado_cap,
        })

    epp_obligatorios = list(
        CategoriaEPP.objects.filter(empresa_id=empresa_id, activo=True, obligatorio_terreno=True)
    )
    entregas_epp = list(
        EntregaEPP.objects.filter(empresa_id=empresa_id, trabajador_id=trabajador_id).select_related("categoria_epp")
    )
    epp_evaluados = []
    for cat in epp_obligatorios:
        ents = [e for e in entregas_epp if e.categoria_epp_id == cat.pk]
        activo_epp = any(
            e.estado in ("entregado", "renovado") and (not e.fecha_vencimiento or e.fecha_vencimiento >= hoy)
            for e in ents
        )
        epp_evaluados.append({
            "categoria_epp_id": str(cat.pk),
            "nombre": cat.nombre,
            "estado": "vigente" if activo_epp else "faltante",
        })

    cap_oblig = [c for c in cap_evaluadas if c["obligatorio"]]
    cap_ok = sum(1 for c in cap_oblig if c["estado"] == "vigente")
    epp_ok = sum(1 for e in epp_evaluados if e["estado"] == "vigente")

    observaciones = []
    if not doc_comp["habilitado_documentalmente"]:
        observaciones.append("Documentación obligatoria incompleta o vencida.")
    if cap_ok < len(cap_oblig):
        observaciones.append("Capacitaciones obligatorias pendientes o vencidas.")
    if epp_ok < len(epp_evaluados):
        observaciones.append("Entrega de EPP obligatorio pendiente o vencida.")

    if not asignaciones:
        estado_preventivo = "con_observaciones"
        estado_label = "Con observaciones (sin asignación activa)"
    elif (
        not doc_comp["habilitado_documentalmente"]
        or doc_comp["vencidos"] > 0
        or doc_comp["rechazados"] > 0
        or cap_ok < len(cap_oblig)
    ):
        estado_preventivo = "no_habilitado"
        estado_label = "No habilitado"
    elif observaciones:
        estado_preventivo = "con_observaciones"
        estado_label = "Con observaciones"
    else:
        estado_preventivo = "habilitado"
        estado_label = "Habilitado"

    return {
        "trabajador_id": str(trabajador_id),
        "empresa_id": str(empresa_id),
        "estado_preventivo": estado_preventivo,
        "estado_habilitacion": estado_preventivo,
        "estado_label": estado_label,
        "observaciones": observaciones,
        "documental": {
            "porcentaje": doc_comp["porcentaje_cumplimiento"],
            "habilitado": doc_comp["habilitado_documentalmente"],
            "total_obligatorios": doc_comp["total_obligatorios"],
            "aprobados": doc_comp["aprobados"],
            "vencidos": doc_comp["vencidos"],
            "faltantes": doc_comp["faltantes"],
        },
        "capacitaciones": {
            "total_obligatorias": len(cap_oblig),
            "vigentes": cap_ok,
            "detalle": cap_evaluadas,
        },
        "epp": {
            "total_obligatorios": len(epp_evaluados),
            "vigentes": epp_ok,
            "detalle": epp_evaluados,
        },
    }


def calcular_dashboard_cumplimiento(
    empresa_id,
    obra_id=None,
    cargo_id=None,
    estado_filtro=None,
    authorized_obras=None,
    hoy=None,
):
    """Calcula indicadores ejecutivos y de cumplimiento por empresa y obra (Etapa 10)."""
    hoy = hoy or timezone.localdate()

    obras_qs = EmpresaObra.objects.filter(empresa_id=empresa_id).select_related("obra")
    if authorized_obras is not None:
        obras_qs = obras_qs.filter(obra_id__in=authorized_obras)
    if obra_id:
        obras_qs = obras_qs.filter(obra_id=obra_id)
    enlaces_obras = list(obras_qs)
    obra_ids_permitidas = [e.obra_id for e in enlaces_obras]

    trabajadores_qs = Trabajador.objects.filter(empresa_id=empresa_id, activo=True)
    if obra_id:
        trabajadores_qs = trabajadores_qs.filter(asignaciones_obras__obra_id=obra_id).distinct()
    elif authorized_obras is not None:
        trabajadores_qs = trabajadores_qs.filter(asignaciones_obras__obra_id__in=obra_ids_permitidas).distinct()
    if cargo_id:
        trabajadores_qs = trabajadores_qs.filter(asignaciones_obras__cargo_id=cargo_id).distinct()

    trabajadores = list(trabajadores_qs.order_by("apellido_paterno", "nombres"))

    resumen_trabajadores = []
    trab_habilitados_doc = 0
    trab_habilitados_prev = 0
    total_req_trab = 0
    total_aprob_trab = 0
    total_pend_trab = 0
    total_rech_trab = 0
    total_venc_trab = 0
    total_falt_trab = 0

    for w in trabajadores:
        comp = calcular_cumplimiento_trabajador(empresa_id, w.pk, obra_id=obra_id, hoy=hoy)
        prev = calcular_habilitacion_preventiva(empresa_id, w.pk, obra_id=obra_id, hoy=hoy)
        est_item = (
            "habilitado"
            if comp["habilitado_documentalmente"]
            else ("vencido" if comp["vencidos"] > 0 else ("pendiente" if comp["pendientes"] > 0 else "incompleto"))
        )
        if estado_filtro and estado_filtro != est_item and estado_filtro != prev["estado_preventivo"]:
            continue
        if comp["habilitado_documentalmente"]:
            trab_habilitados_doc += 1
        if prev["estado_preventivo"] == "habilitado":
            trab_habilitados_prev += 1
        total_req_trab += comp["total_obligatorios"]
        total_aprob_trab += comp["aprobados"]
        total_pend_trab += comp["pendientes"]
        total_rech_trab += comp["rechazados"]
        total_venc_trab += comp["vencidos"]
        total_falt_trab += comp["faltantes"]

        cap_pend_w = max(
            0,
            int(prev["capacitaciones"]["total_obligatorias"]) - int(prev["capacitaciones"]["vigentes"]),
        )
        resumen_trabajadores.append({
            "trabajador_id": w.pk,
            "nombre": f"{w.nombres} {w.apellido_paterno} {w.apellido_materno}".strip(),
            "porcentaje_cumplimiento": comp["porcentaje_cumplimiento"],
            "total_obligatorios": comp["total_obligatorios"],
            "aprobados": comp["aprobados"],
            "pendientes": comp["pendientes"],
            "rechazados": comp["rechazados"],
            "vencidos": comp["vencidos"],
            "faltantes": comp["faltantes"],
            "capacitaciones_pendientes": cap_pend_w,
            "habilitado_documentalmente": comp["habilitado_documentalmente"],
            "estado_preventivo": prev["estado_preventivo"],
            "estado_preventivo_label": prev["estado_label"],
        })

    equipos_qs = Equipo.objects.filter(empresa_id=empresa_id, activo=True)
    if obra_id:
        equipos_qs = equipos_qs.filter(asignaciones__obra_id=obra_id).distinct()
    equipos = list(equipos_qs)
    equipos_habilitados = 0
    equipos_con_vencidos = 0
    resumen_equipos = []
    for eq in equipos:
        c_eq = calcular_cumplimiento_equipo(empresa_id, eq.pk, obra_id=obra_id, hoy=hoy)
        if c_eq["habilitado_operacion"] and eq.estado == "operativo":
            equipos_habilitados += 1
        if c_eq["vencidos"] > 0:
            equipos_con_vencidos += 1
        resumen_equipos.append({
            "equipo_id": str(eq.pk),
            "codigo": eq.codigo,
            "nombre": eq.nombre,
            "tipo_equipo": eq.tipo_equipo,
            "estado_operativo": eq.estado,
            "porcentaje_cumplimiento": c_eq["porcentaje_cumplimiento"],
            "vencidos": c_eq["vencidos"],
            "faltantes": c_eq["faltantes"],
            "habilitado_operacion": c_eq["habilitado_operacion"] and eq.estado == "operativo",
        })

    cumplimiento_empresa = calcular_cumplimiento_empresa(empresa_id, obra_id=obra_id, hoy=hoy)

    alertas_qs = AlertaVencimiento.objects.filter(empresa_id=empresa_id, leida=False)
    if obra_id:
        alertas_qs = alertas_qs.filter(obra_id=obra_id)
    elif authorized_obras is not None:
        alertas_qs = alertas_qs.filter(models.Q(obra__isnull=True) | models.Q(obra_id__in=obra_ids_permitidas))

    por_obra = []
    for enlace in enlaces_obras:
        ob = enlace.obra
        asig_vigentes = AsignacionTrabajadorObra.objects.filter(
            empresa_id=empresa_id,
            obra=ob,
            fecha_inicio__lte=hoy,
        ).filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy)).count()
        eq_vigentes = AsignacionEquipoObra.objects.filter(
            empresa_id=empresa_id,
            obra=ob,
            fecha_inicio__lte=hoy,
        ).filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy)).count()
        ultimo_pdr = (
            ChecklistEvaluacion.objects.filter(semana__obra=ob)
            .select_related("semana")
            .order_by("-semana__numero", "-updated_at")
            .first()
        )
        alertas_obra = alertas_qs.filter(obra=ob).count()
        por_obra.append({
            "obra_id": ob.pk,
            "obra_nombre": ob.nombre,
            "activa": ob.activa,
            "trabajadores_asignados": asig_vigentes,
            "equipos_asignados": eq_vigentes,
            "alertas_activas": alertas_obra,
            "ultimo_informe_pdr": {
                "id": ultimo_pdr.pk,
                "semana_numero": ultimo_pdr.semana.numero if ultimo_pdr.semana_id else None,
                "fecha": (
                    ultimo_pdr.updated_at.date().isoformat()
                    if getattr(ultimo_pdr, "updated_at", None)
                    else (
                        ultimo_pdr.semana.fecha_fin.isoformat()
                        if ultimo_pdr.semana_id and getattr(ultimo_pdr.semana, "fecha_fin", None)
                        else hoy.isoformat()
                    )
                ),
                "evaluado_por": ultimo_pdr.evaluado_por,
            } if ultimo_pdr else None,
        })

    pct_global_trab = (
        round((total_aprob_trab / total_req_trab) * 100, 1)
        if total_req_trab > 0
        else 100.0
    )

    return {
        "empresa_id": str(empresa_id),
        "fecha_corte": hoy.isoformat(),
        "kpis": {
            "obras_activas": sum(1 for o in por_obra if o["activa"]),
            "trabajadores_evaluados": len(resumen_trabajadores),
            "trabajadores_habilitados_doc": trab_habilitados_doc,
            "trabajadores_habilitados_prev": trab_habilitados_prev,
            "porcentaje_cumplimiento_trabajadores": pct_global_trab,
            "porcentaje_cumplimiento_empresa": cumplimiento_empresa["porcentaje_cumplimiento"],
            "equipos_activos": len(resumen_equipos),
            "equipos_habilitados": equipos_habilitados,
            "equipos_con_vencidos": equipos_con_vencidos,
            "capacitaciones_pendientes": sum(w["capacitaciones_pendientes"] for w in resumen_trabajadores),
            "documentos_aprobados": total_aprob_trab,
            "documentos_pendientes": total_pend_trab,
            "documentos_rechazados": total_rech_trab,
            "documentos_vencidos": total_venc_trab,
            "documentos_faltantes": total_falt_trab,
            "alertas_no_leidas": alertas_qs.count(),
        },
        "cumplimiento_empresa": cumplimiento_empresa,
        "por_obra": por_obra,
        "obras": por_obra,
        "trabajadores": resumen_trabajadores,
        "equipos": resumen_equipos,
    }


