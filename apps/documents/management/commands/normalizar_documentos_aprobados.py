"""Comando idempotente para normalizar documentos aprobados sin evidencia (T4.6)."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.authorization.models import RegistroAuditoria
from apps.documents.models import DocumentoTrabajador


class Command(BaseCommand):
    help = "Normaliza documentos aprobados sin archivo pasándolos a pendiente y vincula version_aprobada cuando existe evidencia."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra los documentos a normalizar sin persistir cambios.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        revertidos = 0
        vinculados = 0

        aprobados = DocumentoTrabajador.objects.filter(estado="aprobado").select_related("empresa")
        for doc in aprobados:
            ultima_version = doc.archivos.order_by("-version").first()
            if ultima_version is None:
                revertidos += 1
                if not dry_run:
                    with transaction.atomic():
                        doc.estado = "pendiente"
                        doc.revisado_por = None
                        doc.revisado_en = None
                        doc.version_aprobada = None
                        doc.save(
                            update_fields=[
                                "estado",
                                "revisado_por",
                                "revisado_en",
                                "version_aprobada",
                            ]
                        )
                        RegistroAuditoria.objects.create(
                            empresa=doc.empresa,
                            actor=None,
                            accion="documentos.trabajador.normalizar_sin_evidencia",
                            entidad="DocumentoTrabajador",
                            entidad_id=str(doc.pk),
                            detalle={"estado_anterior": "aprobado", "estado_nuevo": "pendiente"},
                        )
            elif doc.version_aprobada_id != ultima_version.pk:
                vinculados += 1
                if not dry_run:
                    doc.version_aprobada = ultima_version
                    doc.save(update_fields=["version_aprobada"])

        modo = " (DRY-RUN)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Normalización completada{modo}: {revertidos} pasados a pendiente sin evidencia, {vinculados} vinculados a su última versión."
            )
        )

