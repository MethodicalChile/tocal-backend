import json
import re
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from intranet import models as m
from intranet import private_storage as storage


def values(model, row):
    names = {f.attname for f in model._meta.fields}
    result = {}
    for k, v in row.items():
        key = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
        if key in names:
            result[key] = v
    return result


class Command(BaseCommand):
    help = "Carga la demo completa de Angol y ventas en una base Django vacía."

    @transaction.atomic
    def handle(self, *args, **options):
        if m.Obra.objects.exists() or m.User.objects.exists():
            raise CommandError("La base Django ya tiene datos. El seed no sobrescribe información.")
        assets = settings.BASE_DIR / "seed-assets"
        data = json.loads((assets / "angol.json").read_text())
        users = {}
        for email, name, role in [
            ("gerencia@tocal.cl", "Gerencia Tocal", "gerencia"),
            ("cmunoz@tocal.cl", "Carlos Muñoz Sanhueza", "admin_obra"),
            ("crios@tocal.cl", "Carlos Ríos Rosales", "experto_pdr"),
            ("lectura@tocal.cl", "Usuario Lectura", "lectura"),
        ]:
            users[role] = m.User.objects.create_user(
                username=email, email=email, name=name, rol=role, password="tocal2026"
            )
        obra = m.Obra.objects.create(
            nombre="EDS ARAMCO ANGOL",
            razon_social="CONSTRUCTORA TOCAL LTDA",
            rut="76.022.955-5",
            servicio="CONSTRUCCIÓN EDS ARAMCO ANGOL",
            direccion="Angol",
            mandante="Aramco",
            inicio_contrato="2025-12-01",
            asesor_pdr=users["experto_pdr"].name,
            adm_contrato=users["admin_obra"].name,
            fecha_programa_aprobado="2026-01-27",
            **values(m.Obra, data["obra"]),
        )
        for role, user in users.items():
            if role != "gerencia":
                m.ObraUsuario.objects.create(obra=obra, user=user)
        weeks = {}
        for w in data["semanas"]:
            week = m.Semana.objects.create(obra=obra, **values(m.Semana, w))
            weeks[week.numero] = week
            m.Dotacion.objects.create(semana=week, dotacion_femenina=1, **values(m.Dotacion, w))
        last = weeks[max(weeks)]
        evaluation = m.ChecklistEvaluacion.objects.create(
            semana=last, evaluado_por=users["experto_pdr"].name
        )
        for row in data["checklist"]["items"]:
            item = m.ChecklistItem.objects.create(**values(m.ChecklistItem, row))
            m.ChecklistRespuesta.objects.create(
                evaluacion=evaluation,
                item=item,
                estado=row["estado"],
                observacion=row["observacion"],
            )
        for row in data["curvas"]:
            curve = m.Curva.objects.create(obra=obra, **values(m.Curva, row))
            m.PuntoCurva.objects.bulk_create(
                [m.PuntoCurva(curva=curve, **values(m.PuntoCurva, p)) for p in row["puntos"]]
            )
        for key, model in [
            ("actividades", m.Actividad),
            ("estadosPago", m.EstadoPago),
            ("adicionales", m.Adicional),
            ("rdi", m.Rdi),
        ]:
            model.objects.bulk_create([model(obra=obra, **values(model, row)) for row in data[key]])
        report_data = json.loads((assets / "informe-demo.json").read_text())
        m.Informe.objects.create(obra=obra, semana=last, autor=users["admin_obra"], **report_data)
        for i, path in enumerate(sorted(assets.glob("*.jpg"))):
            problem = path.name.startswith("problema")
            if not problem and not path.name.startswith("obra-"):
                continue
            photo = m.Foto(
                obra=obra,
                fecha="2026-09-09" if problem else "2026-09-11",
                etiqueta="problema" if problem else "avance",
                subido_por=users["admin_obra"],
                created_at=datetime(2026, 9, 11, 12, i, tzinfo=dt_timezone.utc),
            )
            photo.storage_path = f"obras/{obra.pk}/fotos/{photo.pk}.jpg"
            storage.write_bytes(photo.storage_path, path.read_bytes(), "image/jpeg")
            photo.save()
        documents = []
        for row in json.loads((assets / "ventas.json").read_text()):
            v = values(m.Venta, row)
            v.update(afecto_uf=v["afecto"] / v["uf_dia"], total_uf=v["total"] / v["uf_dia"])
            if "ARAMCO ANGOL" in (v.get("obra") or "").upper():
                v["obra_ref"] = obra
            documents.append(m.Venta(**v))
        m.Venta.objects.bulk_create(documents, batch_size=200)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo lista: {len(weeks)} semanas, {len(documents)} ventas. Clave de demo: tocal2026"
            )
        )
