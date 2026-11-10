"""Comando programable e idempotente para detectar vencimientos y generar alertas (T6.4)."""
from django.core.management.base import BaseCommand

from apps.documents.services import sincronizar_alertas_vencimiento


class Command(BaseCommand):
    help = "Detecta documentos vencidos y próximos a vencer por empresa sin duplicar alertas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa-id",
            type=str,
            default=None,
            help="UUID opcional de la empresa a evaluar.",
        )

    def handle(self, *args, **options):
        empresa_id = options.get("empresa_id")
        resumen = sincronizar_alertas_vencimiento(empresa_id=empresa_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Alertas evaluadas ({resumen['fecha']}): {resumen['creadas']} creadas, {resumen['actualizadas']} actualizadas."
            )
        )

