from django.core.management.base import BaseCommand

from apps.authorization.models import Empresa
from apps.documents.seed_tocal import sembrar_catalogos_base_tocal


class Command(BaseCommand):
    help = "Puebla de forma idempotente los catálogos oficiales de TOCAL (cargos, tipos documentales, requisitos, capacitaciones y EPP)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa-id",
            dest="empresa_id",
            help="UUID de una empresa específica (por defecto aplica a todas las empresas activas).",
        )

    def handle(self, *args, **options):
        empresa_id = options.get("empresa_id")
        qs = Empresa.objects.filter(activa=True)
        if empresa_id:
            qs = qs.filter(pk=empresa_id)

        empresas = list(qs)
        if not empresas:
            self.stdout.write(self.style.WARNING("No se encontraron empresas activas para sembrar catálogos."))
            return

        for emp in empresas:
            res = sembrar_catalogos_base_tocal(emp.pk)
            self.stdout.write(
                self.style.SUCCESS(
                    f"[{emp.nombre}] Cargos: +{res['cargos_creados']} | "
                    f"Tipos Doc: +{res['tipos_documentales_creados']} | "
                    f"Requisitos Doc: +{res['requisitos_documentales_creados']} | "
                    f"Capacitaciones: +{res['tipos_capacitacion_creados']} | "
                    f"Req. Cap: +{res['requisitos_capacitacion_creados']} | "
                    f"Categorías EPP: +{res['categorias_epp_creadas']}"
                )
            )
