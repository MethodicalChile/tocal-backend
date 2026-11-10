"""Comando para verificar la configuración y privacidad real de Supabase Storage / almacenamiento privado (T12.1)."""
import hashlib
from uuid import uuid4

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from urllib.parse import quote

from intranet import private_storage


class Command(BaseCommand):
    help = "Verifica configuración de almacenamiento privado y opcionalmente realiza prueba roundtrip."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roundtrip",
            action="store_true",
            help="Ejecuta subida, lectura, verificación SHA-256, rechazo público y borrado de archivo de prueba.",
        )

    def handle(self, *args, **options):
        info = private_storage.verify_configuration()
        self.stdout.write(f"Backend activo: {info['backend']}")
        if not info["configured"]:
            raise CommandError("El almacenamiento privado no está completamente configurado.")

        if not options["roundtrip"]:
            self.stdout.write(self.style.SUCCESS("Configuración básica verificada (sin roundtrip)."))
            return

        probe_key = f"healthcheck/{uuid4().hex}.pdf"
        probe_bytes = b"%PDF-1.4\n% TOCAL storage verification probe\n%%EOF\n"
        expected_sha = hashlib.sha256(probe_bytes).hexdigest()

        try:
            private_storage.write_bytes(probe_key, probe_bytes, mime="application/pdf")
            recovered = private_storage.read_bytes(probe_key)
            if hashlib.sha256(recovered).hexdigest() != expected_sha:
                raise CommandError("El hash SHA-256 del archivo recuperado no coincide.")

            if private_storage.enabled():
                bucket = quote(settings.SUPABASE_STORAGE_BUCKET, safe="")
                relative = quote(probe_key, safe="/")
                public_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{relative}"
                with httpx.Client(timeout=15, follow_redirects=False) as client:
                    resp = client.get(public_url)
                if resp.status_code == 200:
                    raise CommandError("ALERTA CRÍTICA: El bucket de Supabase permite acceso público sin autenticación.")
                self.stdout.write(f"Acceso público no autenticado denegado correctamente (HTTP {resp.status_code}).")
        finally:
            try:
                private_storage.delete(probe_key)
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS("Verificación roundtrip de almacenamiento privado exitosa."))

