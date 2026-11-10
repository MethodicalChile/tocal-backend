"""Agrega permisos específicos complementarios para empresas, aprobación documental,
equipos, EPP y alertas, manteniendo sincronizado el rol protegido administrador_general.
"""
from django.db import migrations


PERMISOS_NUEVOS = [
    ("empresas", "Empresas", "ver"),
    ("empresas", "Empresas", "editar"),
    ("documentos", "Documentos", "aprobar"),
    ("equipos", "Equipos", "desactivar"),
    ("epp", "Entrega de EPP", "ver"),
    ("epp", "Entrega de EPP", "crear"),
    ("epp", "Entrega de EPP", "editar"),
    ("alertas", "Alertas y vencimientos", "ver"),
    ("alertas", "Alertas y vencimientos", "configurar"),
]


def crear_permisos_complementarios(apps, schema_editor):
    Permiso = apps.get_model("authorization", "Permiso")
    Rol = apps.get_model("authorization", "Rol")
    RolPermiso = apps.get_model("authorization", "RolPermiso")
    alias = schema_editor.connection.alias

    for modulo, nombre_modulo, accion in PERMISOS_NUEVOS:
        codigo = f"{modulo}.{accion}"
        Permiso.objects.using(alias).get_or_create(
            codigo=codigo,
            defaults={
                "modulo": modulo,
                "accion": accion,
                "nombre": f"{nombre_modulo}: {accion.replace('_', ' ')}",
                "descripcion": "Capacidad administrable por rol y ámbito.",
                "activo": True,
            },
        )

    # Sincroniza los roles protegidos administrador_general existentes con todos los permisos activos.
    permisos_activos = list(Permiso.objects.using(alias).filter(activo=True))
    for rol in Rol.objects.using(alias).filter(codigo="administrador_general", protegido=True, activo=True):
        existentes = set(
            RolPermiso.objects.using(alias)
            .filter(rol=rol)
            .values_list("permiso_id", flat=True)
        )
        nuevos = [
            RolPermiso(rol=rol, permiso=permiso)
            for permiso in permisos_activos
            if permiso.pk not in existentes
        ]
        if nuevos:
            RolPermiso.objects.using(alias).bulk_create(nuevos)


class Migration(migrations.Migration):
    dependencies = [("authorization", "0003_permisos_informes_edicion")]
    operations = [
        migrations.RunPython(crear_permisos_complementarios, migrations.RunPython.noop),
    ]

