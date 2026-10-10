"""Protege tablas y secuencias Django en el esquema public de Supabase.

El esquema público de Supabase puede tener grants predefinidos para los roles
Data API. Este comando debe ejecutarse después de migrar Django, pero NO
sustituye una revisión de las políticas/grants existentes en el proyecto.
"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Aplica RLS y elimina privilegios Data API sobre tablas Django de public."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Solo se permite PostgreSQL/Supabase.")

        with connection.cursor() as cursor:
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
            roles = {row[0] for row in cursor.fetchall()}
            if roles != {"anon", "authenticated"}:
                raise CommandError("No se encontraron los roles estándar de Supabase.")

            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            tables = {row[0] for row in cursor.fetchall()}
            managed = {model._meta.db_table for model in apps.get_models() if model._meta.managed}
            # Incluye django_session, django_migrations, permisos y el admin,
            # además de las tablas propias de intranet.
            protected = {name for name in tables if name in managed or name.startswith(("django_", "auth_", "tocal_"))}
            if not protected:
                raise CommandError("No se encontraron tablas Django para proteger en public.")

            for table in sorted(protected):
                ident = connection.ops.quote_name(table)
                cursor.execute(f"ALTER TABLE public.{ident} ENABLE ROW LEVEL SECURITY")
                cursor.execute(f"REVOKE ALL PRIVILEGES ON TABLE public.{ident} FROM anon, authenticated")
                self.stdout.write(f"RLS + REVOKE: {table}")

            # Protege secuencias del framework; no interferir con secuencias
            # que pertenezcan a aplicaciones independientes del mismo schema.
            cursor.execute("""
                SELECT DISTINCT seq.relname
                FROM pg_class seq
                JOIN pg_namespace ns ON ns.oid = seq.relnamespace
                JOIN pg_depend dep ON dep.objid = seq.oid AND dep.deptype IN ('a', 'i')
                JOIN pg_class tab ON tab.oid = dep.refobjid
                JOIN pg_namespace tns ON tns.oid = tab.relnamespace
                WHERE seq.relkind = 'S' AND ns.nspname = 'public'
                  AND tns.nspname = 'public'
                  AND tab.relname = ANY(%s)
            """, [list(protected)])
            for (seq,) in cursor.fetchall():
                ident = connection.ops.quote_name(seq)
                cursor.execute(f"REVOKE ALL PRIVILEGES ON SEQUENCE public.{ident} FROM anon, authenticated")

            # Estos grants se aplican únicamente a futuros objetos creados
            # por el rol que ejecuta el comando. Verificar propietarios en QA.
            cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated")
            cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated")

        self.stdout.write(self.style.SUCCESS(
            "Protección aplicada. Prueba accesos anon/authenticated desde la Data API, "
            "y vuelve a ejecutar después de cada migración."
        ))
