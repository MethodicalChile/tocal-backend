"""Copia las tablas anteriores sin modificar el origen."""

import json
from datetime import timezone as dt_timezone
from uuid import NAMESPACE_URL, uuid5

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, models, transaction
from django.utils import timezone

from intranet import models as m

TABLES = [
    ("obras", m.Obra),
    ("obra_usuarios", m.ObraUsuario),
    ("semanas_obra", m.Semana),
    ("dotacion_semanal", m.Dotacion),
    ("checklist_items", m.ChecklistItem),
    ("checklist_evaluaciones", m.ChecklistEvaluacion),
    ("checklist_respuestas", m.ChecklistRespuesta),
    ("curvas_s", m.Curva),
    ("puntos_curva", m.PuntoCurva),
    ("actividades_programa", m.Actividad),
    ("estados_pago", m.EstadoPago),
    ("adicionales", m.Adicional),
    ("rdi", m.Rdi),
    ("informes", m.Informe),
    ("obra_fotos", m.Foto),
    ("informe_fotos", m.InformeFoto),
    ("ventas_documentos", m.Venta),
]


class Command(BaseCommand):
    help = "Copia las tablas originales de Next.js a Django y verifica todos los registros. Requiere destino vacío."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Comprueba la migración y revierte las inserciones.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tables = set(connection.introspection.table_names())
        required = {"user", "account", *(name for name, _ in TABLES)}
        missing = required - tables
        if missing:
            raise CommandError("Faltan tablas de origen: " + ", ".join(sorted(missing)))
        if m.User.objects.exists() or any(model.objects.exists() for _, model in TABLES):
            raise CommandError(
                "El destino Django debe estar vacío. No se sobrescriben datos; no ejecutes seed_demo antes de importar."
            )
        if connection.vendor == "postgresql":
            # Bloquea las tablas durante la copia para leer un estado consistente.
            names = ", ".join(connection.ops.quote_name(name) for name in sorted(required))
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {names} IN SHARE MODE")

        def read(table):
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM " + connection.ops.quote_name(table))
                names = [c[0] for c in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]

        accounts = {
            a["user_id"]: a["password"]
            for a in read("account")
            if a["provider_id"] == "credential" and a["password"]
        }
        users = read("user")
        for row in users:
            user = m.User(
                id=row["id"],
                username=row["email"],
                email=row["email"],
                name=row["name"],
                rol=row["rol"],
                legacy_password=accounts.get(row["id"], ""),
            )
            created = row.get("created_at")
            if created:
                user.date_joined = (
                    timezone.make_aware(created, dt_timezone.utc)
                    if timezone.is_naive(created)
                    else created
                )
            user.set_unusable_password()
            user.save()
        self.stdout.write(f"user: {len(users)} usuarios copiados")
        total = len(users)
        for table, model in TABLES:
            records = read(table)
            expected = []
            for row in records:
                values = {}
                for field in model._meta.concrete_fields:
                    if field.column not in row:
                        continue
                    value = row[field.column]
                    if isinstance(field, models.JSONField) and isinstance(value, str):
                        value = json.loads(value)
                    if (
                        isinstance(field, models.DateTimeField)
                        and value is not None
                        and timezone.is_naive(value)
                    ):
                        # Los timestamps heredados están en UTC, aunque no guardan zona horaria.
                        value = timezone.make_aware(value, dt_timezone.utc)
                    values[field.attname] = value
                if "id" not in values:
                    identity = "|".join(str(row[k]) for k in sorted(row))
                    values["id"] = str(uuid5(NAMESPACE_URL, table + ":" + identity))
                expected.append(values)
            model.objects.bulk_create([model(**values) for values in expected], batch_size=200)
            if model.objects.count() != len(records):
                raise CommandError(f"Conteo distinto en {table}; se revierte la copia.")
            # Verifica cada campo copiado, además del total de filas.
            actual = {obj.pk: obj for obj in model.objects.all()}
            for values in expected:
                obj = actual[values["id"]]
                for field, value in values.items():
                    if getattr(obj, field) != value:
                        raise CommandError(
                            f"Validación falló en {table}.{field}; se revierte la copia."
                        )
            total += len(records)
            self.stdout.write(f"{table}: {len(records)} registros verificados")
        if options["dry_run"]:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Simulación correcta: {total} registros. Sin cambios guardados."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Migración completa: {total} registros verificados. Tablas originales conservadas."
                )
            )
