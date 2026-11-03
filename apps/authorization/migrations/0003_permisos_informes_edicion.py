"""Agregar permisos explícitos de modificación y eliminación de informes.

No se otorgan estos permisos automáticamente a ningún rol existente.
"""
from django.db import migrations


def crear_permisos(apps, schema_editor):
    Permiso = apps.get_model("authorization", "Permiso")
    alias = schema_editor.connection.alias
    for accion in ("editar", "eliminar"):
        Permiso.objects.using(alias).get_or_create(
            codigo=f"informes.{accion}",
            defaults={
                "modulo": "informes",
                "accion": accion,
                "nombre": f"Informes: {accion}",
                "descripcion": "Capacidad administrable por rol y ámbito.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("authorization", "0002_catalogo_permisos")]
    operations = [migrations.RunPython(crear_permisos, migrations.RunPython.noop)]
