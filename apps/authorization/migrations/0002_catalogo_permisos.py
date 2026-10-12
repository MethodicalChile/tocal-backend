"""Catálogo inicial de acciones conocido por el backend.

NO se crean asignaciones de roles ni se alteran usuarios/obras existentes.
Los administradores gestionarán las relaciones RolPermiso desde la API futura.
"""
from django.db import migrations


MODULOS = {
    "obras": ("Obras", ("ver", "crear", "editar", "desactivar")),
    "resumen": ("Resumen", ("ver",)),
    "pdr": ("Prevención", ("ver", "editar", "aprobar")),
    "avance": ("Avance", ("ver", "editar")),
    "edp": ("Estados de pago", ("ver", "editar", "aprobar")),
    "adicionales": ("Adicionales", ("ver", "editar")),
    "rdi": ("RDI", ("ver", "editar")),
    "fotos": ("Fotografías", ("ver", "crear", "eliminar")),
    "informes": ("Informes", ("ver", "crear", "descargar", "aprobar")),
    "ventas": ("Ventas", ("ver", "editar", "exportar")),
    "empleados": ("Empleados", ("ver", "ver_sensibles", "crear", "editar", "desactivar", "exportar")),
    "documentos": ("Documentos", ("ver", "crear", "editar", "descargar", "eliminar", "ver_sensibles")),
    "capacitaciones": ("Capacitaciones", ("ver", "crear", "editar", "evaluar")),
    "equipos": ("Equipos", ("ver", "crear", "editar")),
    "roles": ("Roles y permisos", ("ver", "administrar")),
    "usuarios": ("Usuarios", ("ver", "administrar")),
    "auditoria": ("Auditoría", ("ver",)),
}


def crear_permisos(apps, schema_editor):
    Permiso = apps.get_model("authorization", "Permiso")
    alias = schema_editor.connection.alias
    for modulo, (nombre_modulo, acciones) in MODULOS.items():
        for accion in acciones:
            codigo = f"{modulo}.{accion}"
            Permiso.objects.using(alias).get_or_create(
                codigo=codigo,
                defaults={
                    "modulo": modulo,
                    "accion": accion,
                    "nombre": f"{nombre_modulo}: {accion.replace('_', ' ')}",
                    "descripcion": "Capacidad administrable por rol y ámbito.",
                },
            )


class Migration(migrations.Migration):
    dependencies = [("authorization", "0001_initial")]
    operations = [
        migrations.RunPython(crear_permisos, migrations.RunPython.noop),
    ]
