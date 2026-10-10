import os
import subprocess
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea un respaldo PostgreSQL antes de migrar los datos."

    def handle(self, *args, **options):
        if not settings.DEBUG and os.getenv("ALLOW_LOCAL_UNENCRYPTED_BACKUP", "0") != "1":
            raise CommandError(
                "Respaldo local sin cifrado deshabilitado en producción. "
                "Configura backups cifrados y restauraciones desde Supabase."
            )
        db = settings.DATABASES["default"]
        if "postgresql" not in db["ENGINE"]:
            raise CommandError("Este respaldo requiere PostgreSQL.")
        directory = settings.MEDIA_ROOT / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"tocal-before-django-{datetime.now():%Y%m%d-%H%M%S}.dump"
        environment = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or ""),
                       "PGSSLMODE": os.getenv("DB_SSLMODE", "require")}
        command = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(target),
            "--host",
            str(db.get("HOST") or "localhost"),
            "--port",
            str(db.get("PORT") or 5432),
            "--username",
            str(db.get("USER") or "postgres"),
            str(db["NAME"]),
        ]
        try:
            subprocess.run(command, env=environment, check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            target.unlink(missing_ok=True)
            raise CommandError(
                "No se pudo respaldar PostgreSQL. Comprueba pg_dump y la conexión."
            ) from exc
        target.chmod(0o600)
        self.stdout.write(
            self.style.SUCCESS(f"Respaldo creado: {target} ({target.stat().st_size} bytes)")
        )
