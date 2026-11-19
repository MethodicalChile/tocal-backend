"""Comando idempotente para poblar una Demo Integral de TOCAL en todos los módulos.

Carga datos realistas y coherentes sin borrar cuentas existentes:
1. Empresa 'Constructora Tocal Limitada' (RUT 76.022.955-5) y catálogos oficiales DS 44 / MINSAL / 21 Cargos.
2. Usuarios demo por rol (Admin/Gerencia, Prevencionista Alejandro Nilo, Admin Obra Gonzalo Castillo, Administrativo Iván Gajardo).
3. 3 Obras conectadas a la empresa:
   - EDS ARAMCO ANGOL (con curvas S, semanas, dotación DS 67, checklist, EDP, adicionales, RDI, fotos e informe semanal).
   - Enlace Vial Ruta 5 Sur — Agencia Linares.
   - Edificio Corporativo Tocal — Sucursal Santiago.
4. Nómina de 10 trabajadores con RUT Módulo 11 válido en los 3 estados del Semáforo (Verde, Amarillo y Rojo).
5. Evidencias PDF válidas con hash SHA-256 en documentos de trabajador, empresa y equipos.
6. Capacitaciones, difusiones PTS con evaluación (3 preguntas), Charla 5 Minutos / AST y entregas de EPP firmadas.
7. Flota de 4 equipos/maquinarias asignados a obra + Checklists digitales en terreno (RF-12).
8. Alertas de vencimiento activas en la campana superior (RF-13), Libro de Ventas y solicitudes ARCO+ (Ley 21.719).
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.authorization.models import (
    AsignacionRol,
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
    Permiso,
    RegistroAuditoria,
    Rol,
    RolPermiso,
)
from apps.documents.models import (
    ArchivoDocumentoEmpresa,
    ArchivoDocumentoEquipo,
    ArchivoDocumentoTrabajador,
    AsignacionEquipoObra,
    CapacitacionTrabajador,
    CategoriaEPP,
    DocumentoEmpresa,
    DocumentoEquipo,
    DocumentoTrabajador,
    EntregaEPP,
    Equipo,
    RevisionDocumentoEmpresa,
    RevisionDocumentoEquipo,
    RevisionDocumentoTrabajador,
    TipoCapacitacion,
    TipoDocumento,
)
from apps.documents.seed_tocal import sembrar_catalogos_base_tocal
from apps.documents.services import sincronizar_alertas_vencimiento
from intranet import models as m
from intranet import private_storage as storage


MINIMAL_PDF_TEMPLATE = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >> endobj\n"
    b"4 0 obj << /Length 68 >> stream\n"
    b"BT /F1 12 Tf 72 720 Td (EVIDENCIA OFICIAL CONSTRUCTORA TOCAL LTDA - DEMO) Tj ET\n"
    b"endstream endobj\n"
    b"xref\n0 5\n0000000000 65535 f \n"
    b"trailer << /Size 5 /Root 1 0 R >>\nstartxref\n260\n%%EOF\n"
)


def _camel_to_snake_values(model, row):
    names = {f.attname for f in model._meta.fields}
    result = {}
    for k, v in row.items():
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
        if key in names:
            result[key] = v
    return result


def ensure_company_base_roles(empresa):
    permisos_activos = list(Permiso.objects.filter(activo=True))
    rol_admin, _ = Rol.objects.get_or_create(
        empresa=empresa,
        codigo="administrador_general",
        defaults={
            "nombre": "Administrador General",
            "descripcion": "Acceso administrativo y operacional completo en la empresa.",
            "activo": True,
            "protegido": True,
        },
    )
    existentes = set(rol_admin.permisos_asignados.values_list("permiso_id", flat=True))
    nuevos = [RolPermiso(rol=rol_admin, permiso=p) for p in permisos_activos if p.pk not in existentes]
    if nuevos:
        RolPermiso.objects.bulk_create(nuevos)

    roles_operativos = [
        ("prevencionista", "Prevencionista de Riesgos (PDR)", "Gestión documental, capacitaciones, EPP, checklists y cumplimiento DS 44."),
        ("administrador_obra", "Jefe / Administrador de Obra", "Supervisión integral de obra, avance físico, personal y cumplimiento."),
        ("supervisor_terreno", "Supervisor / Portería Terreno", "Consulta rápida en terreno, escáner QR, checklists e informes operacionales."),
    ]
    for cod, nom, desc in roles_operativos:
        rol_op, _ = Rol.objects.get_or_create(
            empresa=empresa,
            codigo=cod,
            defaults={"nombre": nom, "descripcion": desc, "activo": True, "protegido": False},
        )
        ex_op = set(rol_op.permisos_asignados.values_list("permiso_id", flat=True))
        nuevos_op = [RolPermiso(rol=rol_op, permiso=p) for p in permisos_activos if p.pk not in ex_op]
        if nuevos_op:
            RolPermiso.objects.bulk_create(nuevos_op)


class Command(BaseCommand):
    help = "Carga datos fake/demo completos e idempotentes en todos los módulos de TOCAL."

    def handle(self, *args, **options):
        hoy = timezone.localdate()
        with transaction.atomic():
            # 1. Empresa principal
            empresa = Empresa.objects.filter(activa=True).first()
            if not empresa:
                empresa = Empresa.objects.create(
                    nombre="Constructora Tocal Limitada",
                    rut="76.022.955-5",
                    activa=True,
                )
            elif not empresa.rut:
                empresa.rut = "76.022.955-5"
                empresa.save(update_fields=["rut"])

            ensure_company_base_roles(empresa)
            sembrar_catalogos_base_tocal(empresa.pk)

            # 2. Usuarios de demostración por perfil
            usuarios_cfg = [
                ("admin@tocal.cl", "Administrador General TOCAL", "gerencia", True, "administrador_general"),
                ("anilo@tocal.cl", "Alejandro Nilo (Jefe Prevención PDR)", "experto_pdr", False, "prevencionista"),
                ("gcastillo@tocal.cl", "Gonzalo Castillo (Gerente de Proyectos)", "admin_obra", False, "administrador_obra"),
                ("igajardo@tocal.cl", "Iván Gajardo (Gestión de Personas)", "admin_obra", False, "administrador_obra"),
                ("porteria@tocal.cl", "Supervisor Terreno / Portería", "lectura", False, "supervisor_terreno"),
            ]
            users_map = {}
            for email, name, rol_base, is_super, rol_rbac_cod in usuarios_cfg:
                u, _ = m.User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": email,
                        "name": name,
                        "rol": rol_base,
                        "is_superuser": is_super,
                        "is_staff": is_super,
                        "is_active": True,
                    },
                )
                u.name = name
                u.rol = rol_base
                u.is_active = True
                if is_super:
                    u.is_superuser = True
                    u.is_staff = True
                u.set_password("Tocal2026!Admin")
                u.save()
                users_map[email] = u

                memb, _ = MembresiaEmpresa.objects.get_or_create(
                    empresa=empresa, usuario=u, defaults={"activa": True}
                )
                rol_obj = Rol.objects.filter(empresa=empresa, codigo=rol_rbac_cod).first()
                if not rol_obj:
                    rol_obj = Rol.objects.filter(empresa=empresa, codigo="administrador_general").first()
                if rol_obj:
                    AsignacionRol.objects.get_or_create(
                        membresia=memb, rol=rol_obj, empresa_obra=None, defaults={"activa": True}
                    )

            # Garantizar que jimmygallardo04@gmail.com también tenga membresía activa y rol admin
            jimmy = m.User.objects.filter(email="jimmygallardo04@gmail.com").first()
            if jimmy:
                jm, _ = MembresiaEmpresa.objects.get_or_create(
                    empresa=empresa, usuario=jimmy, defaults={"activa": True}
                )
                rol_adm = Rol.objects.filter(empresa=empresa, codigo="administrador_general").first()
                if rol_adm:
                    AsignacionRol.objects.get_or_create(
                        membresia=jm, rol=rol_adm, empresa_obra=None, defaults={"activa": True}
                    )

            admin_user = users_map["admin@tocal.cl"]
            pdr_user = users_map["anilo@tocal.cl"]
            obra_user = users_map["gcastillo@tocal.cl"]

            # 3. Obras de demostración (Angol + Linares + Santiago)
            seed_dir = settings.BASE_DIR.parent / "Tocal-intranet" / "seed-assets"
            obra_angol = m.Obra.objects.filter(nombre="EDS ARAMCO ANGOL").first()
            if not obra_angol and (seed_dir / "angol.json").exists():
                data_angol = json.loads((seed_dir / "angol.json").read_text(encoding="utf-8"))
                obra_angol = m.Obra.objects.create(
                    nombre="EDS ARAMCO ANGOL",
                    razon_social="CONSTRUCTORA TOCAL LTDA",
                    rut="76.022.955-5",
                    servicio="CONSTRUCCIÓN EDS ARAMCO ANGOL",
                    direccion="Av. O'Higgins 1420, Angol",
                    mandante="Aramco Chile",
                    inicio_contrato="2025-12-01",
                    asesor_pdr=pdr_user.name,
                    adm_contrato=obra_user.name,
                    fecha_programa_aprobado="2026-01-27",
                    **_camel_to_snake_values(m.Obra, data_angol["obra"]),
                )
                weeks = {}
                for w in data_angol["semanas"]:
                    week = m.Semana.objects.create(obra=obra_angol, **_camel_to_snake_values(m.Semana, w))
                    weeks[week.numero] = week
                    m.Dotacion.objects.create(semana=week, dotacion_femenina=2, **_camel_to_snake_values(m.Dotacion, w))
                last_week = weeks[max(weeks)]
                evaluation = m.ChecklistEvaluacion.objects.create(
                    semana=last_week, evaluado_por=pdr_user.name
                )
                for row in data_angol["checklist"]["items"]:
                    item, _ = m.ChecklistItem.objects.get_or_create(
                        codigo=row["codigo"],
                        defaults=_camel_to_snake_values(m.ChecklistItem, row),
                    )
                    m.ChecklistRespuesta.objects.create(
                        evaluacion=evaluation,
                        item=item,
                        estado=row["estado"],
                        observacion=row["observacion"],
                    )
                for row in data_angol["curvas"]:
                    curve = m.Curva.objects.create(obra=obra_angol, **_camel_to_snake_values(m.Curva, row))
                    m.PuntoCurva.objects.bulk_create(
                        [m.PuntoCurva(curva=curve, **_camel_to_snake_values(m.PuntoCurva, p)) for p in row["puntos"]]
                    )
                for key, model_cls in [
                    ("actividades", m.Actividad),
                    ("estadosPago", m.EstadoPago),
                    ("adicionales", m.Adicional),
                    ("rdi", m.Rdi),
                ]:
                    model_cls.objects.bulk_create(
                        [model_cls(obra=obra_angol, **_camel_to_snake_values(model_cls, row)) for row in data_angol[key]]
                    )
                if (seed_dir / "informe-demo.json").exists():
                    report_data = json.loads((seed_dir / "informe-demo.json").read_text(encoding="utf-8"))
                    m.Informe.objects.create(obra=obra_angol, semana=last_week, autor=obra_user, **report_data)
                for i, path in enumerate(sorted(seed_dir.glob("*.jpg"))[:12]):
                    problem = path.name.startswith("problema")
                    if not problem and not path.name.startswith("obra-"):
                        continue
                    photo = m.Foto(
                        obra=obra_angol,
                        fecha="2026-09-09" if problem else "2026-09-11",
                        etiqueta="problema" if problem else "avance",
                        sector="Sector Canopy y Playa de Combustibles" if not problem else "Excavación Estanques",
                        caption=f"Registro fotográfico de terreno #{i + 1} — {path.stem}",
                        subido_por=obra_user,
                        created_at=datetime(2026, 9, 11, 12, i, tzinfo=dt_timezone.utc),
                    )
                    photo.storage_path = f"obras/{obra_angol.pk}/fotos/{photo.pk}.jpg"
                    storage.write_bytes(photo.storage_path, path.read_bytes(), "image/jpeg")
                    photo.save()
            elif not obra_angol:
                obra_angol = m.Obra.objects.create(
                    nombre="EDS ARAMCO ANGOL",
                    razon_social="CONSTRUCTORA TOCAL LTDA",
                    rut="76.022.955-5",
                    servicio="CONSTRUCCIÓN EDS ARAMCO ANGOL",
                    direccion="Angol",
                    mandante="Aramco",
                    inicio_contrato="2026-01-15",
                    asesor_pdr=pdr_user.name,
                    adm_contrato=obra_user.name,
                    monto_contractual_uf=18500,
                    activa=True,
                )

            obra_linares, _ = m.Obra.objects.get_or_create(
                nombre="ENLACE VIAL RUTA 5 SUR — AGENCIA LINARES",
                defaults={
                    "razon_social": "CONSTRUCTORA TOCAL LTDA",
                    "rut": "76.123.456-0",
                    "servicio": "Obras Viales, Movimiento de Tierras y Hormigones",
                    "direccion": "Ruta 5 Sur Km 302, Linares",
                    "mandante": "Sociedad Concesionaria del Maule S.A.",
                    "inicio_contrato": date(2026, 3, 1),
                    "termino_contrato": date(2027, 2, 28),
                    "asesor_pdr": pdr_user.name,
                    "asesor_mutual": "Asociación Chilena de Seguridad (ACHS)",
                    "adm_contrato": obra_user.name,
                    "monto_contractual_uf": 24800.0,
                    "anticipo_uf": 2480.0,
                    "activa": True,
                },
            )

            obra_santiago, _ = m.Obra.objects.get_or_create(
                nombre="CENTRO LOGÍSTICO Y OFICINA CENTRAL SANTIAGO",
                defaults={
                    "razon_social": "CONSTRUCTORA TOCAL LTDA",
                    "rut": "76.543.210-K",
                    "servicio": "Edificación Industrial y Galpones Estructurales",
                    "direccion": "Av. Américo Vespucio 2850, Quilicura, Santiago",
                    "mandante": "Inmobiliaria Logística Andina SpA",
                    "inicio_contrato": date(2026, 5, 10),
                    "termino_contrato": date(2027, 4, 30),
                    "asesor_pdr": pdr_user.name,
                    "asesor_mutual": "Asociación Chilena de Seguridad (ACHS)",
                    "adm_contrato": obra_user.name,
                    "monto_contractual_uf": 32400.0,
                    "anticipo_uf": 3240.0,
                    "activa": True,
                },
            )

            for ob in m.Obra.objects.all():
                EmpresaObra.objects.get_or_create(empresa=empresa, obra=ob)
                for u_obj in users_map.values():
                    m.ObraUsuario.objects.get_or_create(obra=ob, user=u_obj)

            # Asegurar catálogo de ChecklistItem de Prevención desde angol.json
            if (seed_dir / "angol.json").exists():
                data_angol_chk = json.loads((seed_dir / "angol.json").read_text(encoding="utf-8"))
                for row in data_angol_chk.get("checklist", {}).get("items", []):
                    m.ChecklistItem.objects.get_or_create(
                        codigo=row["codigo"],
                        defaults=_camel_to_snake_values(m.ChecklistItem, row),
                    )
            checklist_items_all = list(m.ChecklistItem.objects.filter(activo=True).order_by("orden"))

            # Poblar seguimiento completo (semanas, dotación, curvas S, actividades, EDP, adicionales y RDI) en Linares, Santiago y cualquier otra obra sin semanas
            obras_extra_cfg = [
                (
                    obra_linares,
                    [(0.10, 0.11), (0.22, 0.235), (0.35, 0.348), (0.48, 0.492), (0.62, 0.635), (0.75, 0.742)],
                    [
                        (1, 0, "ENLACE VIAL RUTA 5 SUR — AGENCIA LINARES", True, 240, None, None, None, None),
                        (2, 1, "MOVIMIENTO DE TIERRAS Y TERRAPLENES", False, 60, 0.30, 1.0, 1.0, "ok"),
                        (3, 1, "OBRAS DE ARTE Y DRENAJE TRANSVERSAL", False, 75, 0.25, 0.85, 0.88, "adelanto"),
                        (4, 1, "BASE ESTABILIZADA Y CARPETA ASFÁLTICA", False, 65, 0.30, 0.55, 0.52, "atraso"),
                        (5, 1, "SEÑALIZACIÓN VIAL, DEFENSAS Y SEGURIDAD", False, 40, 0.15, 0.20, 0.20, "ok"),
                    ],
                    [
                        (1, "Marzo 2026", 3200.0, "FAC-10421", "pagado"),
                        (2, "Abril 2026", 4500.0, "FAC-10489", "pagado"),
                        (3, "Mayo 2026", 5100.0, "FAC-10540", "aprobado"),
                        (4, "Junio 2026", 4200.0, None, "presentado"),
                    ],
                ),
                (
                    obra_santiago,
                    [(0.08, 0.085), (0.19, 0.20), (0.32, 0.33), (0.46, 0.475), (0.60, 0.615), (0.74, 0.76)],
                    [
                        (1, 0, "CENTRO LOGÍSTICO Y OFICINA CENTRAL SANTIAGO", True, 260, None, None, None, None),
                        (2, 1, "FUNDACIONES Y RADIERES INDUSTRIALES POSTENSADOS", False, 65, 0.28, 1.0, 1.0, "ok"),
                        (3, 1, "ESTRUCTURA METÁLICA Y CUBIERTA GALPONES", False, 80, 0.34, 0.82, 0.85, "adelanto"),
                        (4, 1, "INSTALACIONES ELÉCTRICAS, CLIMA Y RED INCENDIO", False, 60, 0.22, 0.58, 0.60, "ok"),
                        (5, 1, "TERMINACIONES OFICINA CENTRAL Y URBANIZACIÓN", False, 55, 0.16, 0.35, 0.34, "ok"),
                    ],
                    [
                        (1, "Mayo 2026", 4800.0, "FAC-10601", "pagado"),
                        (2, "Junio 2026", 6200.0, "FAC-10678", "facturado"),
                        (3, "Julio 2026", 5900.0, None, "presentado"),
                    ],
                ),
            ]
            for ob_other in m.Obra.objects.exclude(pk__in=[obra_angol.pk, obra_linares.pk, obra_santiago.pk]):
                if not ob_other.monto_contractual_uf:
                    ob_other.monto_contractual_uf = 14500.0
                    ob_other.anticipo_uf = 1450.0
                    ob_other.asesor_pdr = pdr_user.name
                    ob_other.adm_contrato = obra_user.name
                    ob_other.save()
                obras_extra_cfg.append((
                    ob_other,
                    [(0.12, 0.12), (0.28, 0.30), (0.45, 0.46), (0.64, 0.65), (0.80, 0.82)],
                    [
                        (1, 0, ob_other.nombre.upper(), True, 180, None, None, None, None),
                        (2, 1, "INSTALACIÓN DE FAENAS Y CIERRE PERIMETRAL", False, 30, 0.20, 1.0, 1.0, "ok"),
                        (3, 1, "MOVIMIENTO DE TIERRAS Y FUNDACIONES", False, 50, 0.35, 0.90, 0.92, "adelanto"),
                        (4, 1, "OBRA GRUESA Y MONTAJE ESTRUCTURAL", False, 60, 0.30, 0.65, 0.65, "ok"),
                        (5, 1, "TERMINACIONES E INSTALACIONES", False, 40, 0.15, 0.30, 0.28, "ok"),
                    ],
                    [
                        (1, "Mes 1", 2900.0, "FAC-20101", "pagado"),
                        (2, "Mes 2", 3800.0, "FAC-20145", "aprobado"),
                    ],
                ))

            for ob_extra, cur_points, acts_cfg, edps_cfg in obras_extra_cfg:
                for num in range(1, len(cur_points) + 1):
                    sem, _ = m.Semana.objects.get_or_create(
                        obra=ob_extra,
                        numero=num,
                        defaults={
                            "fecha_inicio": hoy - timedelta(days=(len(cur_points) + 1 - num) * 7),
                            "fecha_fin": hoy - timedelta(days=(len(cur_points) - num) * 7 - 1),
                        },
                    )
                    m.Dotacion.objects.get_or_create(
                        semana=sem,
                        defaults={
                            "personal_operativo": 18 + num,
                            "personal_adm": 4,
                            "hh_operativas": (18 + num) * 45,
                            "hh_adm": 4 * 45,
                            "subcontratos": 2,
                            "personal_sc": 8,
                            "hh_sc": 8 * 45,
                            "incidentes": 1 if num == 2 else 0,
                            "accidentes": 0,
                            "dias_perdidos": 0,
                            "dotacion_femenina": 3,
                        },
                    )
                curva_ex, _ = m.Curva.objects.get_or_create(
                    obra=ob_extra,
                    variante="general",
                    defaults={"nombre": "Curva S General", "dias_habiles_programa": 240},
                )
                for idx, (prog, real) in enumerate(cur_points, start=1):
                    m.PuntoCurva.objects.update_or_create(
                        curva=curva_ex,
                        semana=idx,
                        defaults={
                            "fecha": hoy - timedelta(days=(len(cur_points) + 1 - idx) * 7),
                            "programado": prog,
                            "real": real,
                            "reprogramado": prog,
                        },
                    )
                if not m.Actividad.objects.filter(obra=ob_extra).exists():
                    for orden, nivel, desc, es_res, dur, peso, pct_p, pct_a, st in acts_cfg:
                        m.Actividad.objects.create(
                            obra=ob_extra,
                            orden=orden,
                            nivel=nivel,
                            descripcion=desc,
                            es_resumen=es_res,
                            duracion=dur,
                            inicio=hoy - timedelta(days=90 - orden * 10),
                            fin=hoy + timedelta(days=orden * 25),
                            peso=peso,
                            pct_programa=pct_p,
                            pct_actual=pct_a,
                            status=st,
                        )
                if not m.EstadoPago.objects.filter(obra=ob_extra).exists():
                    for num_edp, per, monto, fac, est in edps_cfg:
                        m.EstadoPago.objects.create(
                            obra=ob_extra,
                            numero=num_edp,
                            periodo=per,
                            monto_uf=monto,
                            numero_factura=fac,
                            fecha=hoy - timedelta(days=(5 - num_edp) * 20),
                            estado=est,
                            observacion="Estado de pago revisado y visado por ITO mandante.",
                        )
                adicionales_demo = [
                    (1, "Obras civiles complementarias y refuerzo estructural sector acceso", "aprobado", "Aumento de Obra", 680.0, 650.0, "OC-2026-884"),
                    (2, "Modificación de trazado de canalización eléctrica y cámaras de paso", "aprobado", "Obra Extraordinaria", 420.0, 420.0, "OC-2026-912"),
                    (3, "Mejoramiento de subbase granular y geotextil en zona de carga pesada", "presentado", "Aumento de Obra", 540.0, None, None),
                ]
                for num_ad, desc_ad, est_ad, clas_ad, m_uf, m_ap, oc_num in adicionales_demo:
                    m.Adicional.objects.get_or_create(
                        obra=ob_extra,
                        numero=num_ad,
                        defaults={
                            "descripcion": desc_ad,
                            "fecha_presentacion": hoy - timedelta(days=40 - num_ad * 10),
                            "estado": est_ad,
                            "clasificacion": clas_ad,
                            "monto_uf": m_uf,
                            "monto_aprobado_uf": m_ap,
                            "numero_oc": oc_num,
                            "observaciones": "Documentación técnica y cubicación respaldada por Oficina Técnica.",
                        },
                    )
                rdis_demo = [
                    (1, "Correo Electrónico / Libro de Obra", "PL-EST-04", "Estructuras / Ingeniería", "Confirmación de cota de fundación y empalme de canalizaciones", "respondida", hoy - timedelta(days=35), hoy - timedelta(days=28)),
                    (2, "Plataforma Mandante", "PL-ELE-09", "Instalaciones Eléctricas", "Validación de ubicación de tablero general auxiliar y canalización subterránea", "respondida", hoy - timedelta(days=22), hoy - timedelta(days=16)),
                    (3, "Libro de Obra Digital", "PL-ARQ-12", "Arquitectura / Pavimentos", "Definición de junta de dilatación y sello elastomérico en encuentro de losas", "pendiente", hoy - timedelta(days=6), None),
                ]
                for num_rdi, med_r, ref_r, esp_r, mat_r, est_r, f_env, f_resp in rdis_demo:
                    m.Rdi.objects.get_or_create(
                        obra=ob_extra,
                        numero=num_rdi,
                        defaults={
                            "medio": med_r,
                            "referencia": ref_r,
                            "especialidad": esp_r,
                            "materia": mat_r,
                            "fecha_envio": f_env,
                            "fecha_respuesta": f_resp,
                            "estado": est_r,
                            "responsable": obra_user.name,
                            "respondida_por": "ITO Mandante" if f_resp else None,
                            "observaciones": "Respondida conforme por proyectista." if f_resp else "En espera de pronunciamiento de proyectista.",
                        },
                    )

            # 3.B Poblar Evaluación de Checklist PDR, Fotografías en las 5 categorías e Informes Semanales en TODAS las obras
            seed_jpgs = sorted(seed_dir.glob("obra-*.jpg")) if seed_dir.exists() else []
            prob_jpgs = sorted(seed_dir.glob("problema-*.jpg")) if seed_dir.exists() else []
            if not prob_jpgs and seed_jpgs:
                prob_jpgs = seed_jpgs[-2:]

            photo_templates_by_category = [
                ("avance", "Sector Fundaciones y Radier Principal", "Hormigonado y vibrado de fundaciones estructurales según plano PL-EST-01"),
                ("avance", "Frente de Estructura y Montaje", "Montaje de estructura principal, alineación topográfica y torqueo de pernos"),
                ("avance", "Sector Accesos y Pavimentación", "Compactación de base estabilizada CBR >= 80% y preparación de carpeta de rodado"),
                ("avance", "Canalizaciones y Obras Civiles", "Instalación de ductos subterráneos, cámaras de inspección y relleno compactado"),
                ("seguridad", "Perímetro de Excavación y Accesos", "Cierre perimetral rígido, malla faenera, señalética de riesgos críticos y pasos peatonales"),
                ("seguridad", "Frente de Trabajo en Altura", "Verificación de línea de vida horizontal certificada, arnés de seguridad y doble cabo de vida"),
                ("seguridad", "Zona de Charla 5 Minutos y Estación de Emergencia", "Registro de Charla Diaria de 5 Minutos / AST, estación de hidratación RUVS y extintores PQS"),
                ("calidad", "Laboratorio de Terreno y Control de Hormigón", "Toma de muestras de hormigón en fresco, control de cono de Abrams y confección de probetas"),
                ("calidad", "Recepción de Enfierradura y Moldajes (PAC)", "Liberación de armaduras de refuerzo, recubrimientos y estanqueidad de moldaje junto a ITO"),
                ("problema", "Sector Talud Poniente / Drenaje", "Desmoronamiento puntual de talud por escorrentía de aguas lluvias; se instala entibación y polietileno"),
                ("problema", "Cámara de Empalme Existente", "Interferencia detectada con ducto existente no catastrado en plano; se emite RDI a mandante"),
                ("otra", "Patio de Acopio y Bodega de Obra", "Acopio segregado de materiales, jaula de sustancias peligrosas (DS 43) y acopio de residuos"),
                ("otra", "Vista General de Instalación de Faenas", "Vista panorámica del avance general de obra, oficinas técnicas, comedores y baños DS 594"),
            ]

            for ob_idx, ob_item in enumerate(m.Obra.objects.all()):
                semanas_obra = list(m.Semana.objects.filter(obra=ob_item).order_by("numero"))
                if not semanas_obra:
                    continue
                ultima_semana = semanas_obra[-1]

                # Checklist de Prevención DS 44 en la última semana de cada obra
                if checklist_items_all and not m.ChecklistEvaluacion.objects.filter(semana__obra=ob_item).exists():
                    ev_obj = m.ChecklistEvaluacion.objects.create(
                        semana=ultima_semana,
                        evaluado_por=pdr_user.name,
                        updated_at=timezone.now(),
                    )
                    for idx_it, c_item in enumerate(checklist_items_all):
                        est_it = "cumple"
                        obs_it = "Verificado en terreno conforme estándar DS 44."
                        if idx_it == 14:
                            est_it = "no_cumple"
                            obs_it = "En proceso de actualización de firma de anexo subcontrato; plazo cierre 48 hrs."
                        elif idx_it == 22:
                            est_it = "no_aplica"
                            obs_it = "No aplica en la etapa constructiva actual."
                        m.ChecklistRespuesta.objects.create(
                            evaluacion=ev_obj,
                            item=c_item,
                            estado=est_it,
                            observacion=obs_it,
                        )

                # Fotografías en las 5 categorías ('avance', 'problema', 'seguridad', 'calidad', 'otra')
                existing_tags = set(m.Foto.objects.filter(obra=ob_item).values_list("etiqueta", flat=True))
                missing_tags = {"avance", "problema", "seguridad", "calidad", "otra"} - existing_tags
                if missing_tags and seed_jpgs:
                    for p_idx, (cat_tag, sec_txt, cap_txt) in enumerate(photo_templates_by_category):
                        if cat_tag not in missing_tags and m.Foto.objects.filter(obra=ob_item, etiqueta=cat_tag).count() >= 2:
                            continue
                        # Elegir fecha dentro de las últimas semanas de la obra para que entren en los Informes Semanales
                        target_week = semanas_obra[max(0, len(semanas_obra) - 1 - (p_idx % min(3, len(semanas_obra))))]
                        foto_date = target_week.fecha_inicio + timedelta(days=min(5, p_idx % 6))
                        if cat_tag == "problema" and prob_jpgs:
                            src_path = prob_jpgs[(ob_idx + p_idx) % len(prob_jpgs)]
                        else:
                            src_path = seed_jpgs[(ob_idx * 5 + p_idx) % len(seed_jpgs)]
                        raw_jpg = src_path.read_bytes()
                        photo = m.Foto(
                            obra=ob_item,
                            fecha=foto_date,
                            etiqueta=cat_tag,
                            sector=sec_txt,
                            caption=f"{cap_txt} ({ob_item.nombre})",
                            ancho=1280,
                            alto=960,
                            subido_por=obra_user if cat_tag != "seguridad" else pdr_user,
                            created_at=timezone.now() - timedelta(days=(13 - p_idx)),
                        )
                        photo.storage_path = f"obras/{ob_item.pk}/fotos/{photo.pk}.jpg"
                        storage.write_bytes(photo.storage_path, raw_jpg, "image/jpeg")
                        photo.save()

                # Informes Semanales (hasta 3 informes por obra: 2 emitidos con PDF y 1 en borrador)
                ultimas_tres = semanas_obra[-3:] if len(semanas_obra) >= 3 else semanas_obra
                for w_i, sem_rep in enumerate(ultimas_tres):
                    es_ultimo = (w_i == len(ultimas_tres) - 1)
                    estado_rep = "borrador" if (es_ultimo and len(ultimas_tres) > 1) else "emitido"
                    rep_obj, created_rep = m.Informe.objects.get_or_create(
                        obra=ob_item,
                        semana=sem_rep,
                        defaults={
                            "titulo": f"INFORME SEMANAL N° {sem_rep.numero} — {ob_item.nombre}",
                            "fecha_corte": sem_rep.fecha_fin,
                            "estado": estado_rep,
                            "nota_avance": f"Control de avance físico y preventivo correspondiente a la Semana {sem_rep.numero} ({sem_rep.fecha_inicio} al {sem_rep.fecha_fin}).",
                            "comentarios": [
                                {"texto": f"Se ejecutan partidas críticas de acuerdo al programa maestro vigente en {ob_item.nombre}."},
                                {"texto": "Prevención de Riesgos (DS 44): Se realiza charla diaria de 5 minutos, AST en frentes de trabajo y revisión de arneses/maquinaria sin incidentes."},
                                {"texto": "Control de Calidad (PAC): Se reciben partidas de fundaciones, compactación y trazado junto a ITO Mandante.", "destacado": True},
                                {
                                    "texto": "Coordinaciones de Obra y Oficina Técnica:",
                                    "sub": [
                                        "Seguimiento de estados de pago y control de curva S física versus programada.",
                                        "Gestión de RDI en curso con proyectistas de estructura e instalaciones.",
                                    ],
                                },
                            ],
                            "posibles_problemas": [
                                {"texto": "Condiciones climáticas y precipitaciones puntuales obligaron a reforzar protección de taludes y drenaje perimetral."},
                                {"texto": "Interferencia menor en trazado de canalizaciones resuelta mediante RDI con ITO."},
                            ],
                            "autor": obra_user,
                            "emitido_at": timezone.now() - timedelta(days=(len(ultimas_tres) - w_i) * 7) if estado_rep == "emitido" else None,
                        },
                    )
                    if estado_rep == "emitido" and not rep_obj.pdf_path:
                        pdf_rep_bytes = MINIMAL_PDF_TEMPLATE + f"% informe:{rep_obj.pk}\n".encode("utf-8")
                        pdf_key = f"informes/{rep_obj.pk}/informe-{rep_obj.fecha_corte}.pdf"
                        storage.write_bytes(pdf_key, pdf_rep_bytes, "application/pdf")
                        rep_obj.pdf_path = pdf_key
                        rep_obj.save(update_fields=["pdf_path"])

                    # Vincular fotos de la obra al informe (InformeFoto)
                    fotos_obra = list(m.Foto.objects.filter(obra=ob_item).order_by("-fecha")[:8])
                    for f_idx, f_obj in enumerate(fotos_obra):
                        m.InformeFoto.objects.get_or_create(
                            informe=rep_obj,
                            foto=f_obj,
                            defaults={
                                "incluir": True,
                                "seccion": "problema" if f_obj.etiqueta == "problema" else "obra",
                                "orden": f_idx + 1,
                            },
                        )

            # 4. Libro de Ventas desde seed-assets si está vacío
            if not m.Venta.objects.exists() and (seed_dir / "ventas.json").exists():
                ventas_raw = json.loads((seed_dir / "ventas.json").read_text(encoding="utf-8"))
                ventas_objs = []
                for row in ventas_raw:
                    v = _camel_to_snake_values(m.Venta, row)
                    v.update(afecto_uf=v["afecto"] / v["uf_dia"], total_uf=v["total"] / v["uf_dia"])
                    if "ARAMCO ANGOL" in (v.get("obra") or "").upper():
                        v["obra_ref"] = obra_angol
                    ventas_objs.append(m.Venta(**v))
                m.Venta.objects.bulk_create(ventas_objs, batch_size=200)

            # 5. Función auxiliar para adjuntar un PDF válido con SHA-256 y aprobar un documento
            def _attach_and_approve_worker_doc(doc_obj, estado_final="aprobado", motivo_rechazo=""):
                if not doc_obj.archivos.exists():
                    pdf_bytes = MINIMAL_PDF_TEMPLATE + f"% doc:{doc_obj.pk}\n".encode("utf-8")
                    key = f"documents/{empresa.pk}/{doc_obj.pk}/{uuid4().hex}.pdf"
                    storage.write_bytes(key, pdf_bytes, mime="application/pdf")
                    arch = ArchivoDocumentoTrabajador.objects.create(
                        documento=doc_obj,
                        version=1,
                        clave_privada=key,
                        nombre_original=f"respaldo_{doc_obj.tipo_documento.codigo}.pdf",
                        tipo_mime="application/pdf",
                        tamano_bytes=len(pdf_bytes),
                        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                        subido_por=pdr_user,
                    )
                else:
                    arch = doc_obj.archivos.order_by("-version").first()

                doc_obj.estado = estado_final
                doc_obj.version_aprobada = arch if estado_final == "aprobado" else None
                doc_obj.motivo_rechazo = motivo_rechazo if estado_final == "rechazado" else ""
                doc_obj.revisado_por = pdr_user
                doc_obj.revisado_en = timezone.now()
                doc_obj.save()
                RevisionDocumentoTrabajador.objects.get_or_create(
                    documento=doc_obj,
                    archivo=arch,
                    estado=estado_final,
                    defaults={
                        "observaciones": motivo_rechazo or "Respaldo verificado conforme DS 44.",
                        "revisado_por": pdr_user,
                    },
                )

            def _attach_and_approve_company_doc(doc_obj):
                if not doc_obj.archivos.exists():
                    pdf_bytes = MINIMAL_PDF_TEMPLATE + f"% company_doc:{doc_obj.pk}\n".encode("utf-8")
                    key = f"documents_company/{empresa.pk}/{doc_obj.pk}/{uuid4().hex}.pdf"
                    storage.write_bytes(key, pdf_bytes, mime="application/pdf")
                    arch = ArchivoDocumentoEmpresa.objects.create(
                        documento=doc_obj,
                        version=1,
                        clave_privada=key,
                        nombre_original=f"corporativo_{doc_obj.tipo_documento.codigo}.pdf",
                        tipo_mime="application/pdf",
                        tamano_bytes=len(pdf_bytes),
                        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                        subido_por=pdr_user,
                    )
                else:
                    arch = doc_obj.archivos.order_by("-version").first()
                doc_obj.estado = "aprobado"
                doc_obj.version_aprobada = arch
                doc_obj.revisado_por = pdr_user
                doc_obj.revisado_en = timezone.now()
                doc_obj.save()
                RevisionDocumentoEmpresa.objects.get_or_create(
                    documento=doc_obj,
                    archivo=arch,
                    estado="aprobado",
                    defaults={"observaciones": "Aprobado por Gerencia y Prevención de Riesgos.", "revisado_por": pdr_user},
                )

            def _attach_and_approve_equipment_doc(doc_obj):
                if not doc_obj.archivos.exists():
                    pdf_bytes = MINIMAL_PDF_TEMPLATE + f"% equip_doc:{doc_obj.pk}\n".encode("utf-8")
                    key = f"documents_equipment/{empresa.pk}/{doc_obj.pk}/{uuid4().hex}.pdf"
                    storage.write_bytes(key, pdf_bytes, mime="application/pdf")
                    arch = ArchivoDocumentoEquipo.objects.create(
                        documento=doc_obj,
                        version=1,
                        clave_privada=key,
                        nombre_original=f"equipo_{doc_obj.tipo_documento.codigo}.pdf",
                        tipo_mime="application/pdf",
                        tamano_bytes=len(pdf_bytes),
                        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                        subido_por=pdr_user,
                    )
                else:
                    arch = doc_obj.archivos.order_by("-version").first()
                doc_obj.estado = "aprobado"
                doc_obj.version_aprobada = arch
                doc_obj.revisado_por = pdr_user
                doc_obj.revisado_en = timezone.now()
                doc_obj.save()
                RevisionDocumentoEquipo.objects.get_or_create(
                    documento=doc_obj,
                    archivo=arch,
                    estado="aprobado",
                    defaults={"observaciones": "Inspección mecánica y documental al día.", "revisado_por": pdr_user},
                )

            # 6. Documentos Corporativos de Empresa (RIOHS, IPER, DS 44, PTS, Protocolos MINSAL)
            tipos_emp = TipoDocumento.objects.filter(empresa=empresa, categoria="empresa", activo=True)
            for td in tipos_emp:
                doc_e, _ = DocumentoEmpresa.objects.get_or_create(
                    empresa=empresa,
                    tipo_documento=td,
                    obra=None,
                    defaults={
                        "fecha_emision": hoy - timedelta(days=45),
                        "fecha_vencimiento": hoy + timedelta(days=320),
                        "estado": "pendiente",
                        "observaciones": f"Documento corporativo oficial vigente ({td.nombre}). Firmado por Alejandro Nilo, Gonzalo Castillo y Gerencia.",
                        "creado_por": pdr_user,
                    },
                )
                _attach_and_approve_company_doc(doc_e)

            # 7. Trabajadores de Demostración (10 trabajadores con distintos cargos, obras y estados de semáforo)
            cargos_map = {c.codigo: c for c in m.Cargo.objects.filter(empresa=empresa)}
            tipos_doc_trab = {
                t.codigo: t for t in TipoDocumento.objects.filter(empresa=empresa, categoria="trabajador", activo=True)
            }
            tipos_cap = {t.codigo: t for t in TipoCapacitacion.objects.filter(empresa=empresa, activo=True)}
            cats_epp_basicos = list(CategoriaEPP.objects.filter(empresa=empresa, activo=True, obligatorio_terreno=True))

            nomina_demo = [
                # (Nombres, ApPaterno, ApMaterno, RUT_valido_Mod11, cargo_cod, obra_obj, perfil_semaforo, email_user)
                ("Luis Alberto", "Alvear", "Morales", "11.111.111-1", "maestro-primera", obra_angol, "verde", None),
                ("Juan Andrés", "Pérez", "Soto", "12.345.678-5", "trazador", obra_angol, "verde", None),
                ("Pedro Antonio", "Rojas", "Díaz", "15.432.198-K", "operador-maquinaria", obra_angol, "verde", None),
                ("Carlos Alberto", "Muñoz", "Sanhueza", "17.890.123-2", "jefe-terreno", obra_angol, "verde", "gcastillo@tocal.cl"),
                ("Miguel Ángel", "Contreras", "Silva", "19.283.746-3", "conductor-obra", obra_linares, "verde", None),
                ("Roberto Carlos", "Fuentes", "Garrido", "14.253.647-4", "capataz", obra_linares, "verde", None),
                ("Héctor Patricio", "Sepúlveda", "Bravo", "16.543.210-9", "topografo", obra_linares, "amarillo_por_vencer", None),
                ("María Fernanda", "Valdés", "Riquelme", "18.765.432-1", "administrativo-obras", obra_santiago, "verde", "igajardo@tocal.cl"),
                ("Sergio Andrés", "Tapia", "Espinoza", "13.579.246-0", "bodeguero", obra_santiago, "verde", None),
                ("Diego Ignacio", "Cáceres", "Bustamante", "20.123.456-2", "maestro-segunda", obra_angol, "rojo_vencido", None),
                # 12 Trabajadores adicionales cubriendo todos los cargos del organigrama TOCAL
                ("Alejandro Esteban", "Nilo", "Vargas", "10.123.456-8", "jefe-prevencion-riesgos", obra_angol, "verde", "anilo@tocal.cl"),
                ("Camila Paz", "Aravena", "Lagos", "11.222.333-9", "prevencionista-obra", obra_linares, "verde", None),
                ("Rodrigo Ignacio", "Salazar", "Méndez", "12.111.222-1", "administrador-obra", obra_linares, "verde", None),
                ("Carolina Andrea", "Pizarro", "Orellana", "13.222.333-5", "jefe-oficina-tecnica", obra_santiago, "verde", None),
                ("Cristián Eduardo", "Vergara", "Donoso", "14.555.666-K", "supervisor-calidad", obra_angol, "verde", None),
                ("José Manuel", "Henríquez", "Palma", "15.777.888-9", "carpintero", obra_linares, "verde", None),
                ("Claudio César", "Carrasco", "Jara", "16.888.999-2", "albanil", obra_angol, "verde", None),
                ("Mauricio Javier", "Navarro", "Leiva", "17.444.555-9", "soldador", obra_santiago, "verde", None),
                ("Sebastián Nicolás", "Riquelme", "Vera", "18.333.444-1", "electrico-mantencion", obra_santiago, "amarillo_por_vencer", None),
                ("Francisco Javier", "Maldonado", "Pino", "19.666.777-6", "jornal-ayudante", obra_linares, "verde", None),
                ("Valentina Sofía", "Gutiérrez", "Castro", "21.234.567-9", "prevencionista-obra", obra_santiago, "verde", None),
                ("Matías Alejandro", "Venegas", "Saavedra", "22.345.678-2", "jornal-ayudante", obra_santiago, "rojo_vencido", None),
            ]

            for nombres, ap_pat, ap_mat, rut, cargo_cod, obra_dest, modo, user_email in nomina_demo:
                w, _ = m.Trabajador.objects.get_or_create(
                    empresa=empresa,
                    rut=rut,
                    defaults={
                        "nombres": nombres,
                        "apellido_paterno": ap_pat,
                        "apellido_materno": ap_mat,
                        "activo": True,
                        "usuario": users_map.get(user_email) if user_email else None,
                    },
                )
                cargo_obj = cargos_map.get(cargo_cod) or next(iter(cargos_map.values()))
                m.AsignacionTrabajadorObra.objects.get_or_create(
                    empresa=empresa,
                    trabajador=w,
                    obra=obra_dest,
                    fecha_fin__isnull=True,
                    defaults={
                        "cargo": cargo_obj,
                        "fecha_inicio": hoy - timedelta(days=60),
                        "observaciones": f"Asignado a {obra_dest.nombre} como {cargo_obj.nombre}",
                    },
                )

                # Documentos obligatorios para este trabajador
                codigos_docs = ["contrato-trabajo", "cedula-identidad", "odi-das-ds44", "recepcion-riohs", "examen-ocupacional"]
                if cargo_cod in ("maestro-primera", "maestro-segunda", "trazador"):
                    codigos_docs.append("aptitud-altura-fisica")
                if cargo_cod in ("operador-maquinaria", "conductor-obra"):
                    codigos_docs.extend(["licencia-conducir-operador", "aptitud-psicosensometrico"])

                for c_doc in codigos_docs:
                    td = tipos_doc_trab.get(c_doc)
                    if not td:
                        continue
                    # Definir vencimiento según el modo del trabajador para lucir el Semáforo y Alertas
                    if modo == "rojo_vencido" and c_doc in ("aptitud-altura-fisica", "examen-ocupacional"):
                        f_venc = hoy - timedelta(days=12)  # Vencido hace 12 días -> ROJO y alerta
                    elif modo == "amarillo_por_vencer" and c_doc == "examen-ocupacional":
                        f_venc = hoy + timedelta(days=10)  # Vence en 10 días -> Alerta por vencer
                    else:
                        f_venc = (hoy + timedelta(days=240)) if td.requiere_vencimiento else None

                    doc_w, _ = DocumentoTrabajador.objects.get_or_create(
                        empresa=empresa,
                        trabajador=w,
                        tipo_documento=td,
                        defaults={
                            "obra": obra_dest,
                            "fecha_emision": hoy - timedelta(days=50),
                            "fecha_vencimiento": f_venc,
                            "estado": "pendiente",
                            "observaciones": f"Expediente Hombre Nuevo — {td.nombre}",
                            "creado_por": pdr_user,
                        },
                    )
                    doc_w.fecha_vencimiento = f_venc
                    _attach_and_approve_worker_doc(doc_w, estado_final="aprobado")

                # Capacitaciones y PTS del trabajador
                codigos_caps = [
                    "induccion-odi-ds44",
                    "uso-cuidado-epp",
                    "uso-manejo-extintores",
                    "protocolos-minsal-silice-ruido-uv",
                    "pts-excavaciones-difusion",
                    "pts-altura-difusion",
                    "pts-instalaciones-electricas-difusion",
                    "pts-trabajo-caliente-difusion",
                ]
                if cargo_cod in ("maestro-primera", "maestro-segunda", "trazador", "jefe-terreno"):
                    codigos_caps.append("trabajo-altura-fisica")
                if cargo_cod in ("operador-maquinaria", "conductor-obra"):
                    codigos_caps.append("operacion-segura-maquinaria")
                if cargo_cod in ("administrativo-obras",):
                    codigos_caps.append("ergonomia-pausas-activas-oficina")

                for c_cap in codigos_caps:
                    if modo == "rojo_vencido" and c_cap == "trabajo-altura-fisica":
                        # Dejar pendiente este curso en el trabajador en ROJO para mostrar brecha
                        continue
                    tc = tipos_cap.get(c_cap)
                    if not tc:
                        continue
                    CapacitacionTrabajador.objects.get_or_create(
                        empresa=empresa,
                        trabajador=w,
                        tipo_capacitacion=tc,
                        defaults={
                            "obra": obra_dest,
                            "fecha_realizacion": hoy - timedelta(days=30),
                            "fecha_vencimiento": hoy + timedelta(days=335),
                            "horas": tc.horas_sugeridas or 2,
                            "relator": "Alejandro Nilo (Experto PDR TOCAL)",
                            "estado": "vigente",
                            "observaciones": "Evaluación: 100% | Resultado: Aprobado | Asistencia firmada | Prueba DS 44 (3 preguntas): 3/3 correctas (100%)",
                            "registrado_por": pdr_user,
                        },
                    )

                # Entregas de los 5 EPP básicos obligatorios
                for idx_epp, cat_epp in enumerate(cats_epp_basicos):
                    if modo == "rojo_vencido" and idx_epp == 0:
                        # Omitir 1 EPP al trabajador en ROJO para evidenciar falta de EPP
                        continue
                    EntregaEPP.objects.get_or_create(
                        empresa=empresa,
                        trabajador=w,
                        categoria_epp=cat_epp,
                        defaults={
                            "obra": obra_dest,
                            "elemento": cat_epp.nombre,
                            "talla_o_serie": "L / Certificado ISP",
                            "cantidad": 1,
                            "fecha_entrega": hoy - timedelta(days=30),
                            "fecha_vencimiento": hoy + timedelta(days=150),
                            "estado": "entregado",
                            "firmado_recepcion": True,
                            "observaciones": "Kit Hombre Nuevo — Certificado según DS 594 / DS 44.",
                            "entregado_por": pdr_user,
                        },
                    )

            # 8. Flota de Equipos y Maquinaria (RF-11) — 8 equipos distribuidos en las obras
            flota_demo = [
                ("exc-cat-01", "Retroexcavadora Caterpillar 416F2", "Maquinaria Pesada", "Caterpillar", "416F2", "KJ-WB-42", "operativo", obra_angol, "Pedro Antonio Rojas Díaz (Operador)"),
                ("cam-pluma-02", "Camión Pluma Hiab / Mercedes-Benz", "Equipo de Izaje", "Mercedes-Benz", "Atego 1726", "PR-TX-88", "operativo", obra_angol, "Pedro Antonio Rojas Díaz (Operador)"),
                ("cam-obra-03", "Camioneta Doble Cabina 4x4 Obra", "Vehículo Liviano", "Mitsubishi", "L200 Katana", "SW-KL-19", "operativo", obra_linares, "Miguel Ángel Contreras Silva (Conductor)"),
                ("plat-elev-04", "Plataforma Elevadora Tijera Genie", "Trabajo en Altura", "Genie", "GS-2646", "GEN-9941", "operativo", obra_santiago, "Mauricio Javier Navarro Leiva (Operador)"),
                ("exc-kom-05", "Excavadora Oruga Komatsu PC200-8", "Maquinaria Pesada", "Komatsu", "PC200-8M0", "LZ-RT-55", "operativo", obra_linares, "Roberto Carlos Fuentes Garrido (Capataz)"),
                ("rod-hamm-06", "Rodillo Compactador Vibratorio Hamm HD12", "Compactación Vial", "Hamm", "HD12 VV", "HM-8821", "operativo", obra_linares, "Miguel Ángel Contreras Silva (Operador)"),
                ("cam-tolva-07", "Camión Tolva 15m³ Mack Granite", "Transporte de Áridos", "Mack", "Granite GU813", "pl-vk-91".upper(), "operativo", obra_angol, "Pedro Antonio Rojas Díaz (Operador)"),
                ("gen-cumm-08", "Grupo Electrógeno Insonorizado Cummins 110 kVA", "Respaldo Eléctrico", "Cummins", "C110D5", "CUM-4410", "operativo", obra_santiago, "Sebastián Nicolás Riquelme Vera (Eléctrico SEC)"),
            ]
            tipos_doc_eq = list(TipoDocumento.objects.filter(empresa=empresa, categoria="equipo", activo=True))
            equipos_creados = []
            for cod, nom, tipo_eq, marca, mod, pat, est, ob_eq, resp_eq in flota_demo:
                eq, _ = Equipo.objects.get_or_create(
                    empresa=empresa,
                    codigo=cod,
                    defaults={
                        "nombre": nom,
                        "tipo_equipo": tipo_eq,
                        "marca": marca,
                        "modelo": mod,
                        "patente_o_serie": pat,
                        "estado": est,
                        "activo": True,
                    },
                )
                equipos_creados.append((eq, ob_eq))
                AsignacionEquipoObra.objects.get_or_create(
                    empresa=empresa,
                    equipo=eq,
                    obra=ob_eq,
                    fecha_fin__isnull=True,
                    defaults={
                        "responsable": resp_eq,
                        "fecha_inicio": hoy - timedelta(days=45),
                        "observaciones": "Operando en frente principal de obra.",
                    },
                )
                for td_eq in tipos_doc_eq:
                    f_venc_eq = (hoy + timedelta(days=14)) if (cod == "cam-obra-03" and td_eq.codigo == "revision-tecnica-equipo") else (hoy + timedelta(days=180))
                    doc_eq, _ = DocumentoEquipo.objects.get_or_create(
                        empresa=empresa,
                        equipo=eq,
                        tipo_documento=td_eq,
                        defaults={
                            "obra": ob_eq,
                            "fecha_emision": hoy - timedelta(days=40),
                            "fecha_vencimiento": f_venc_eq,
                            "estado": "pendiente",
                            "observaciones": f"Control técnico vigente — {eq.nombre}",
                            "creado_por": pdr_user,
                        },
                    )
                    _attach_and_approve_equipment_doc(doc_eq)

            # 9. Checklists e Inspecciones Digitales en Terreno (RF-12)
            if RegistroAuditoria.objects.filter(empresa=empresa, accion="prevencion.checklist.registrar").count() < 8:
                checklists_demo = [
                    (
                        "Check-list Pre-operacional de Maquinaria / Vehículo",
                        obra_angol,
                        equipos_creados[0][0],
                        "conforme",
                        "Frenos, alarma de retroceso, baliza estroboscópica, extintor PQS 10kg y neumáticos en óptimo estado.",
                        "Equipo autorizado para excavación de zanjas.",
                    ),
                    (
                        "Inspección de Arnés y Sistema de Detención de Caídas (Altura)",
                        obra_angol,
                        None,
                        "conforme",
                        "Revisión de 8 arneses cuerpo completo, argollas D, amortiguadores de impacto y líneas de vida sin desgaste.",
                        "Codificación mensual aplicada.",
                    ),
                    (
                        "Inspección de Herramientas Eléctricas y Tableros Provisionales",
                        obra_linares,
                        None,
                        "con_observaciones",
                        "Se detectó 1 extensión monofásica sin sello de color del mes en sector bodega.",
                        "Extensión retirada de inmediato y reemplazada por eléctrica certificada SEC.",
                    ),
                    (
                        "Inspección de Excavaciones, Taludes y Entibaciones",
                        obra_angol,
                        None,
                        "conforme",
                        "Taludes acuñados, malla faenera perimetral a 1,5m del borde y pasarelas con rodapié instaladas.",
                        "Sin hallazgos críticos.",
                    ),
                    (
                        "Check-list Pre-operacional de Maquinaria / Vehículo",
                        obra_linares,
                        equipos_creados[4][0],
                        "conforme",
                        "Sistema hidráulico sin fugas, orugas con tensión nominal, espejo panorámico y corta-corriente operativos.",
                        "Excavadora habilitada para movimiento de tierras en enlace vial.",
                    ),
                    (
                        "Inspección de Plataforma Elevadora y Trabajo en Altura",
                        obra_santiago,
                        equipos_creados[3][0],
                        "conforme",
                        "Barandas perimetrales, parada de emergencia en canastillo y base, sensores de inclinación operativos.",
                        "Autorizada para montaje eléctrico en galpón principal.",
                    ),
                    (
                        "Inspección de Condiciones Higiénicas, Comedores y Agua Potable (DS 594)",
                        obra_santiago,
                        None,
                        "conforme",
                        "Comedores con piso lavable, refrigeración operativa, servicios higiénicos limpios y dispensadores de bloqueador UV.",
                        "Cumplimiento 100% DS 594.",
                    ),
                    (
                        "Inspección de Señalización Vial y Segregación de Tránsito",
                        obra_linares,
                        equipos_creados[5][0],
                        "conforme",
                        "Barreras New Jersey, conos reflectantes de alta intensidad, paleteros con radio y vestimenta clase 3.",
                        "Frente de compactación segregado conforme manual de carreteras.",
                    ),
                ]
                existing_chk_titles = {
                    (r.detalle or {}).get("tipo_checklist", "") + "|" + str((r.detalle or {}).get("obra_nombre", ""))
                    for r in RegistroAuditoria.objects.filter(empresa=empresa, accion="prevencion.checklist.registrar")
                }
                for tpl, ob_c, eq_c, res_g, hall, med in checklists_demo:
                    sig = f"{tpl}|{ob_c.nombre}"
                    if sig in existing_chk_titles:
                        continue
                    RegistroAuditoria.objects.create(
                        empresa=empresa,
                        actor=pdr_user,
                        accion="prevencion.checklist.registrar",
                        entidad="ChecklistDigital",
                        entidad_id=str(eq_c.pk if eq_c else ob_c.pk),
                        detalle={
                            "tipo_checklist": tpl,
                            "fecha": hoy.isoformat(),
                            "obra_id": str(ob_c.pk),
                            "obra_nombre": ob_c.nombre,
                            "equipo_id": str(eq_c.pk) if eq_c else None,
                            "equipo_nombre": f"{eq_c.nombre} ({eq_c.codigo})" if eq_c else None,
                            "inspector": "Alejandro Nilo (Experto PDR)",
                            "resultado_global": res_g,
                            "items": [],
                            "hallazgos": hall,
                            "medidas_correctivas": med,
                        },
                    )

            # 10. Solicitudes de Privacidad ARCO+ (Ley N° 21.719)
            if not m.SolicitudPrivacidad.objects.exists():
                m.SolicitudPrivacidad.objects.create(
                    usuario=obra_user,
                    tipo="portabilidad",
                    detalle="Solicito copia electrónica estructurada de mis fichas laborales y certificados de capacitación DS 44.",
                    estado="resuelta",
                    closed_at=timezone.now(),
                )
                m.SolicitudPrivacidad.objects.create(
                    usuario=pdr_user,
                    tipo="rectificacion",
                    detalle="Actualización de teléfono de contacto de emergencia y domicilio particular en carpeta laboral.",
                    estado="revision",
                )

            # 11. Sincronizar motor de alertas de vencimiento (Campana 🔔)
            alertas_res = sincronizar_alertas_vencimiento(empresa_id=empresa.pk, hoy=hoy, actor=pdr_user)

        self.stdout.write(
            self.style.SUCCESS(
                f"¡Demo Integral TOCAL cargada exitosamente! "
                f"Obras: {m.Obra.objects.count()} | "
                f"Trabajadores: {m.Trabajador.objects.count()} | "
                f"Equipos: {Equipo.objects.count()} | "
                f"Alertas generadas: {alertas_res}"
            )
        )
