"""Semilla idempotente de catálogos oficiales de TOCAL por empresa.

Basado en el levantamiento documental de la carpeta `documentos/`:
- Organigrama Tocal y 16 perfiles de cargo constructora.
- Tipos documentales por trabajador, empresa y equipo/maquinaria.
- Requisitos documentales base por categoría y cargo.
- Catálogo de capacitaciones PDR (DS 44) y requisitos por cargo.
- Categorías de EPP con vida útil sugerida.
"""
from django.db import transaction

from apps.authorization.models import Empresa, RegistroAuditoria
from apps.documents.models import (
    CategoriaEPP,
    ConfiguracionAlertaEmpresa,
    RequisitoCapacitacion,
    RequisitoDocumental,
    TipoCapacitacion,
    TipoDocumento,
)
from intranet.models import Cargo
from intranet.workforce_api import PERFILES_CARGOS_TOCAL


TIPOS_DOCUMENTALES_TOCAL = [
    # --- TRABAJADOR ---
    {
        "codigo": "contrato-trabajo",
        "nombre": "Contrato de Trabajo Firmado",
        "categoria": "trabajador",
        "descripcion": "Contrato individual de trabajo vigente y firmado por ambas partes.",
        "requiere_vencimiento": False,
    },
    {
        "codigo": "cedula-identidad",
        "nombre": "Cédula de Identidad Vigente",
        "categoria": "trabajador",
        "descripcion": "Copia por ambos lados de cédula de identidad vigente.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "certificado-antecedentes",
        "nombre": "Certificado de Antecedentes",
        "categoria": "trabajador",
        "descripcion": "Certificado de antecedentes para fines especiales vigente.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "afiliacion-previsional",
        "nombre": "Certificado de Afiliación AFP y Salud",
        "categoria": "trabajador",
        "descripcion": "Certificados de afiliación previsional (AFP) y sistema de salud (Fonasa/Isapre).",
        "requiere_vencimiento": False,
    },
    {
        "codigo": "odi-das-ds44",
        "nombre": "Obligación de Informar (ODI / DAS DS 44)",
        "categoria": "trabajador",
        "descripcion": "Registro firmado de inducción e información de riesgos laborales inherentes al cargo.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "recepcion-riohs",
        "nombre": "Recepción de Reglamento Interno (RIOHS)",
        "categoria": "trabajador",
        "descripcion": "Comprobante firmado de entrega del Reglamento Interno de Orden, Higiene y Seguridad.",
        "requiere_vencimiento": False,
    },
    {
        "codigo": "examen-ocupacional",
        "nombre": "Examen Preocupacional / Altura Física",
        "categoria": "trabajador",
        "descripcion": "Certificado de aptitud médica emitido por mutualidad (altura física, espacios confinados o maquinaria).",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "licencia-conducir-operador",
        "nombre": "Licencia de Conducir / Operador (Clase B / D / A4)",
        "categoria": "trabajador",
        "descripcion": "Licencia municipal vigente acorde al vehículo o maquinaria pesada asignada.",
        "requiere_vencimiento": True,
    },
    # --- EMPRESA ---
    {
        "codigo": "riohs-empresa",
        "nombre": "Reglamento Interno de Orden, Higiene y Seguridad (RIOHS)",
        "categoria": "empresa",
        "descripcion": "Reglamento Interno vigente con comprobante de depósito ante Dirección del Trabajo y SEREMI de Salud.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "adhesion-siniestralidad-mutual",
        "nombre": "Certificado de Adhesión y Siniestralidad Mutualidad",
        "categoria": "empresa",
        "descripcion": "Certificado emitido por organismo administrador Ley 16.744 con tasa de cotización y siniestralidad.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "certificado-f30-1",
        "nombre": "Certificado de Cumplimiento Laboral y Previsional (F30-1)",
        "categoria": "empresa",
        "descripcion": "Certificado F30-1 de la Dirección del Trabajo que acredita cumplimiento de obligaciones laborales y previsionales.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "matriz-iper",
        "nombre": "Matriz de Identificación de Peligros y Evaluación de Riesgos (IPER)",
        "categoria": "empresa",
        "descripcion": "Matriz IPER actualizada según procesos constructivos y lineamientos DS 44.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "programa-prevencion-ds44",
        "nombre": "Programa de Gestión Preventiva SST (DS 44)",
        "categoria": "empresa",
        "descripcion": "Programa anual de prevención de riesgos laborales aprobado para la constructora y sus obras.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "plan-emergencia-obra",
        "nombre": "Plan de Emergencia y Evacuación",
        "categoria": "empresa",
        "descripcion": "Procedimiento de respuesta ante emergencias, sismos, incendios y accidentes graves o fatales.",
        "requiere_vencimiento": True,
    },
    # --- EQUIPO ---
    {
        "codigo": "revision-tecnica-equipo",
        "nombre": "Revisión Técnica Vigente",
        "categoria": "equipo",
        "descripcion": "Certificado de revisión técnica o inspección mecánica vigente del vehículo o maquinaria.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "permiso-circulacion-soap",
        "nombre": "Permiso de Circulación y SOAP",
        "categoria": "equipo",
        "descripcion": "Permiso de circulación y Seguro Obligatorio de Accidentes Personales al día.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "mantencion-preventiva-equipo",
        "nombre": "Pauta de Mantención Preventiva Vigente",
        "categoria": "equipo",
        "descripcion": "Registro de última mantención preventiva según horas de uso o kilometraje del fabricante.",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "checklist-preoperacional-equipo",
        "nombre": "Check-list de Inspección Pre-operacional",
        "categoria": "equipo",
        "descripcion": "Verificación de sistemas críticos de seguridad (frenos, luces, alarma de retroceso, extintor).",
        "requiere_vencimiento": True,
    },
    {
        "codigo": "certificacion-operatividad",
        "nombre": "Certificación Técnica de Operatividad / Izaje",
        "categoria": "equipo",
        "descripcion": "Certificación estructural y operativa para equipos críticos de obra.",
        "requiere_vencimiento": True,
    },
]

CAPACITACIONES_TOCAL = [
    {
        "codigo": "induccion-odi-ds44",
        "nombre": "Inducción Hombre Nuevo y ODI (DS 44)",
        "descripcion": "Charla de inducción de seguridad al ingreso, riesgos críticos de obra y medidas preventivas.",
        "horas_sugeridas": 4,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
    {
        "codigo": "uso-manejo-extintores",
        "nombre": "Uso y Manejo de Extintores Portátiles",
        "descripcion": "Capacitación teórico-práctica en prevención de incendios y combate inicial del fuego en obra.",
        "horas_sugeridas": 2,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
    {
        "codigo": "trabajo-altura-fisica",
        "nombre": "Trabajo Seguro en Altura Física y Uso de Arnés",
        "descripcion": "Procedimiento de trabajo seguro sobre andamios, plataformas, bordes de losa y sistemas anticaídas.",
        "horas_sugeridas": 8,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
    {
        "codigo": "uso-cuidado-epp",
        "nombre": "Uso, Selección y Mantención de EPP",
        "descripcion": "Capacitación obligatoria sobre uso correcto e inspección de elementos de protección personal.",
        "horas_sugeridas": 2,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
    {
        "codigo": "operacion-segura-maquinaria",
        "nombre": "Operación Segura de Maquinaria Pesada y Equipos Móviles",
        "descripcion": "Conducción defensiva en faena, segregación hombre-máquina y bloqueo de energías.",
        "horas_sugeridas": 8,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
    {
        "codigo": "primeros-auxilios-emergencias",
        "nombre": "Primeros Auxilios y Actuación ante Accidentes Graves (Circular 3705)",
        "descripcion": "Protocolo de atención primaria y notificación de accidentes graves o fatales en obra.",
        "horas_sugeridas": 4,
        "requiere_vencimiento": True,
        "vigencia_meses": 12,
    },
]

CATEGORIAS_EPP_TOCAL = [
    {
        "codigo": "casco-seguridad",
        "nombre": "Casco de Seguridad con Barbiquejo",
        "descripcion": "Casco certificado clase A/E con arnés interior regulable y barbiquejo de sujeción.",
        "vida_util_meses": 12,
        "requiere_vencimiento": True,
        "obligatorio_terreno": True,
    },
    {
        "codigo": "calzado-seguridad",
        "nombre": "Zapatos / Bototos de Seguridad Dieléctricos",
        "descripcion": "Calzado de seguridad con puntera de protección y planta antideslizante.",
        "vida_util_meses": 6,
        "requiere_vencimiento": True,
        "obligatorio_terreno": True,
    },
    {
        "codigo": "lentes-seguridad",
        "nombre": "Lentes de Seguridad con Filtro UV",
        "descripcion": "Antiparras o lentes herméticos contra impactos de partículas y radiación solar UV.",
        "vida_util_meses": 6,
        "requiere_vencimiento": True,
        "obligatorio_terreno": True,
    },
    {
        "codigo": "guantes-proteccion",
        "nombre": "Guantes de Seguridad Cabritilla / Multiflex",
        "descripcion": "Protección mecánica para manipulación de materiales y herramientas manuales.",
        "vida_util_meses": 3,
        "requiere_vencimiento": True,
        "obligatorio_terreno": True,
    },
    {
        "codigo": "chaleco-reflectante",
        "nombre": "Chaleco Geólogo / Alta Visibilidad",
        "descripcion": "Prenda reflectante obligatoria para tránsito en frentes de trabajo y movimiento de maquinaria.",
        "vida_util_meses": 6,
        "requiere_vencimiento": True,
        "obligatorio_terreno": True,
    },
    {
        "codigo": "protector-auditivo",
        "nombre": "Protección Auditiva (Fono / Tapón Reutilizable)",
        "descripcion": "Protección contra exposición a ruido ocupacional (PREXOR).",
        "vida_util_meses": 6,
        "requiere_vencimiento": True,
        "obligatorio_terreno": False,
    },
    {
        "codigo": "arnes-seguridad",
        "nombre": "Arnés de Seguridad Cuerpo Completo + Doble Cabo de Vida",
        "descripcion": "Sistema personal para detención de caídas en trabajos sobre 1,8 metros de altura.",
        "vida_util_meses": 12,
        "requiere_vencimiento": True,
        "obligatorio_terreno": False,
    },
]


def sembrar_catalogos_base_tocal(empresa_id, actor=None):
    """Puebla de manera idempotente los catálogos oficiales de TOCAL en una empresa."""
    empresa = Empresa.objects.get(pk=empresa_id)
    resumen = {
        "empresa_id": str(empresa.pk),
        "empresa_nombre": empresa.nombre,
        "cargos_creados": 0,
        "tipos_documentales_creados": 0,
        "requisitos_documentales_creados": 0,
        "tipos_capacitacion_creados": 0,
        "requisitos_capacitacion_creados": 0,
        "categorias_epp_creadas": 0,
    }

    with transaction.atomic():
        # 1. Configuración de alertas por defecto
        ConfiguracionAlertaEmpresa.objects.get_or_create(
            empresa=empresa,
            defaults={
                "dias_anticipacion": [30, 15, 7],
                "notificar_vencidos": True,
                "activo": True,
            },
        )

        # 2. Cargos del organigrama y perfiles Tocal
        cargos_map = {}
        for perfil in PERFILES_CARGOS_TOCAL:
            cargo, created = Cargo.objects.get_or_create(
                empresa=empresa,
                codigo=perfil["codigo"],
                defaults={
                    "nombre": perfil["nombre"],
                    "descripcion": perfil["descripcion"],
                    "activo": True,
                },
            )
            if created:
                resumen["cargos_creados"] += 1
            cargos_map[perfil["codigo"]] = cargo

        # 3. Tipos documentales (Trabajador, Empresa, Equipo)
        tipos_doc_map = {}
        for item in TIPOS_DOCUMENTALES_TOCAL:
            td, created = TipoDocumento.objects.get_or_create(
                empresa=empresa,
                codigo=item["codigo"],
                defaults={
                    "nombre": item["nombre"],
                    "categoria": item["categoria"],
                    "descripcion": item["descripcion"],
                    "requiere_vencimiento": item["requiere_vencimiento"],
                    "activo": True,
                },
            )
            if created:
                resumen["tipos_documentales_creados"] += 1
            tipos_doc_map[item["codigo"]] = td

        # 4. Requisitos documentales de Empresa y de Equipo (generales de la empresa)
        codigos_req_empresa_equipo = [
            "riohs-empresa",
            "adhesion-siniestralidad-mutual",
            "certificado-f30-1",
            "matriz-iper",
            "programa-prevencion-ds44",
            "revision-tecnica-equipo",
            "permiso-circulacion-soap",
            "mantencion-preventiva-equipo",
            "checklist-preoperacional-equipo",
        ]
        for cod in codigos_req_empresa_equipo:
            td = tipos_doc_map.get(cod)
            if not td:
                continue
            if not RequisitoDocumental.objects.filter(
                empresa=empresa,
                tipo_documento=td,
                cargo__isnull=True,
                obra__isnull=True,
            ).exists():
                RequisitoDocumental.objects.create(
                    empresa=empresa,
                    tipo_documento=td,
                    cargo=None,
                    obra=None,
                    obligatorio=True,
                    activo=True,
                )
                resumen["requisitos_documentales_creados"] += 1

        # 5. Requisitos documentales por Cargo de Trabajador
        docs_transversales_trabajador = [
            "contrato-trabajo",
            "cedula-identidad",
            "odi-das-ds44",
            "recepcion-riohs",
        ]
        cargos_terreno_altura = {
            "jefe-terreno",
            "jefe-obras",
            "prevencionista-riesgos",
            "topografo",
            "trazador",
            "maestro-primera",
            "maestro-segunda",
            "operador-maquinaria",
        }
        cargos_conduccion = {"operador-maquinaria", "conductor-obra"}

        for cod_cargo, cargo_obj in cargos_map.items():
            codigos_para_cargo = list(docs_transversales_trabajador)
            if cod_cargo in cargos_terreno_altura:
                codigos_para_cargo.append("examen-ocupacional")
            if cod_cargo in cargos_conduccion:
                codigos_para_cargo.append("licencia-conducir-operador")

            for cod_doc in codigos_para_cargo:
                td = tipos_doc_map.get(cod_doc)
                if not td:
                    continue
                if not RequisitoDocumental.objects.filter(
                    empresa=empresa,
                    tipo_documento=td,
                    cargo=cargo_obj,
                    obra__isnull=True,
                ).exists():
                    RequisitoDocumental.objects.create(
                        empresa=empresa,
                        tipo_documento=td,
                        cargo=cargo_obj,
                        obra=None,
                        obligatorio=True,
                        activo=True,
                    )
                    resumen["requisitos_documentales_creados"] += 1

        # 6. Tipos de Capacitación y Requisitos de Capacitación
        tipos_cap_map = {}
        for cap_item in CAPACITACIONES_TOCAL:
            tc, created = TipoCapacitacion.objects.get_or_create(
                empresa=empresa,
                codigo=cap_item["codigo"],
                defaults={
                    "nombre": cap_item["nombre"],
                    "descripcion": cap_item["descripcion"],
                    "horas_sugeridas": cap_item["horas_sugeridas"],
                    "requiere_vencimiento": cap_item["requiere_vencimiento"],
                    "vigencia_meses": cap_item["vigencia_meses"],
                    "activo": True,
                },
            )
            if created:
                resumen["tipos_capacitacion_creados"] += 1
            tipos_cap_map[cap_item["codigo"]] = tc

        # Requisitos de capacitación transversales (sin cargo específico = aplica a todos)
        for cod_cap in ("induccion-odi-ds44", "uso-cuidado-epp", "uso-manejo-extintores"):
            tc = tipos_cap_map.get(cod_cap)
            if tc and not RequisitoCapacitacion.objects.filter(
                empresa=empresa,
                tipo_capacitacion=tc,
                cargo__isnull=True,
                obra__isnull=True,
            ).exists():
                RequisitoCapacitacion.objects.create(
                    empresa=empresa,
                    tipo_capacitacion=tc,
                    cargo=None,
                    obra=None,
                    obligatorio=True,
                    activo=True,
                )
                resumen["requisitos_capacitacion_creados"] += 1

        # Requisitos de capacitación específicos por cargo
        tc_altura = tipos_cap_map.get("trabajo-altura-fisica")
        if tc_altura:
            for cod_c in ("maestro-primera", "maestro-segunda", "trazador", "jefe-terreno", "jefe-obras"):
                c_obj = cargos_map.get(cod_c)
                if c_obj and not RequisitoCapacitacion.objects.filter(
                    empresa=empresa, tipo_capacitacion=tc_altura, cargo=c_obj, obra__isnull=True
                ).exists():
                    RequisitoCapacitacion.objects.create(
                        empresa=empresa,
                        tipo_capacitacion=tc_altura,
                        cargo=c_obj,
                        obra=None,
                        obligatorio=True,
                        activo=True,
                    )
                    resumen["requisitos_capacitacion_creados"] += 1

        tc_maq = tipos_cap_map.get("operacion-segura-maquinaria")
        if tc_maq:
            for cod_c in ("operador-maquinaria", "conductor-obra"):
                c_obj = cargos_map.get(cod_c)
                if c_obj and not RequisitoCapacitacion.objects.filter(
                    empresa=empresa, tipo_capacitacion=tc_maq, cargo=c_obj, obra__isnull=True
                ).exists():
                    RequisitoCapacitacion.objects.create(
                        empresa=empresa,
                        tipo_capacitacion=tc_maq,
                        cargo=c_obj,
                        obra=None,
                        obligatorio=True,
                        activo=True,
                    )
                    resumen["requisitos_capacitacion_creados"] += 1

        # 7. Categorías de EPP
        for epp_item in CATEGORIAS_EPP_TOCAL:
            _, created = CategoriaEPP.objects.get_or_create(
                empresa=empresa,
                codigo=epp_item["codigo"],
                defaults={
                    "nombre": epp_item["nombre"],
                    "descripcion": epp_item["descripcion"],
                    "vida_util_meses": epp_item["vida_util_meses"],
                    "requiere_vencimiento": epp_item["requiere_vencimiento"],
                    "obligatorio_terreno": epp_item["obligatorio_terreno"],
                    "activo": True,
                },
            )
            if created:
                resumen["categorias_epp_creadas"] += 1

        if actor is not None and getattr(actor, "is_authenticated", False):
            RegistroAuditoria.objects.create(
                empresa=empresa,
                actor=actor,
                accion="catalogos.sembrar_base_tocal",
                entidad="Empresa",
                entidad_id=str(empresa.pk),
                detalle=resumen,
            )

    return resumen
