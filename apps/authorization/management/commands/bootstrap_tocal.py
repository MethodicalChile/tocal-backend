"""Bootstrap explícito e idempotente del primer administrador de una empresa.

No altera User.rol, ObraUsuario ni asocia obras implícitamente.
La vista previa (sin --apply) no ejecuta escrituras.
"""
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.authorization.models import (
    AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa,
    Permiso, RegistroAuditoria, Rol, RolPermiso,
)
from intranet.models import Obra

ADMIN_CODE = "administrador_general"
REQUIRED = {"roles.administrar", "usuarios.administrar"}


class Command(BaseCommand):
    help = "Inicializa empresa y administrador RBAC. Vista previa por defecto; --apply escribe."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True, help="Username o ID existente (único)")
        parser.add_argument("--empresa-id", help="UUID de empresa existente")
        parser.add_argument("--empresa-nombre", help="Nombre para crear nueva empresa")
        parser.add_argument("--empresa-rut", help="RUT para nueva empresa (opcional)")
        parser.add_argument("--obra-id", action="append", default=[], help="ID de obra a vincular; repetible")
        parser.add_argument("--apply", action="store_true", help="Aplicar los cambios")
        parser.add_argument("--confirmar", help="Escribir exactamente BOOTSTRAP para confirmar --apply")

    def handle(self, *args, **options):
        if bool(options["empresa_id"]) == bool(options["empresa_nombre"]):
            raise CommandError("Indica solo --empresa-id o --empresa-nombre.")
        if options["empresa_id"] and options["empresa_rut"]:
            raise CommandError("--empresa-rut solo se permite al crear una empresa.")
        if options["apply"] and options["confirmar"] != "BOOTSTRAP":
            raise CommandError("Para escribir utiliza --apply --confirmar BOOTSTRAP.")

        User = get_user_model()
        value = options["usuario"]
        qs = User.objects.filter(username=value)
        if not qs.exists():
            qs = User.objects.filter(pk=value)
        usuario = qs.first()
        if usuario is None or not usuario.is_active:
            raise CommandError("El usuario no existe o está inactivo.")

        empresa = None
        if options["empresa_id"]:
            try:
                empresa_uuid = UUID(options["empresa_id"])
            except (ValueError, TypeError):
                raise CommandError("--empresa-id debe ser UUID válido.")
            empresa = Empresa.objects.filter(pk=empresa_uuid, activa=True).first()
            if not empresa:
                raise CommandError("No existe una empresa activa con ese ID.")
        else:
            nombre = options["empresa_nombre"].strip()
            if not nombre or len(nombre) > 200:
                raise CommandError("Nombre de empresa inválido.")
            rut = (options["empresa_rut"] or "").strip() or None
            if rut and len(rut) > 20:
                raise CommandError("RUT demasiado largo.")
            if rut and Empresa.objects.filter(rut=rut).exists():
                raise CommandError("Ya existe una empresa con ese RUT; utiliza --empresa-id.")
            if Empresa.objects.filter(nombre__iexact=nombre).exists():
                raise CommandError("Ya existe una empresa con ese nombre; utiliza --empresa-id.")

        obras = []
        if len(options["obra_id"]) != len(set(options["obra_id"])):
            raise CommandError("Los ID de obra están duplicados.")
        for obra_id in options["obra_id"]:
            obra = Obra.objects.filter(pk=obra_id).first()
            if not obra:
                raise CommandError(f"No existe la obra {obra_id}.")
            vinculo = EmpresaObra.objects.filter(obra=obra).select_related("empresa").first()
            if vinculo and (not empresa or vinculo.empresa_id != empresa.pk):
                raise CommandError(f"La obra {obra_id} ya está vinculada a {vinculo.empresa.nombre}; no se reasigna.")
            obras.append(obra)

        codigos = set(Permiso.objects.filter(activo=True).values_list("codigo", flat=True))
        if not REQUIRED.issubset(codigos):
            raise CommandError("Faltan permisos administrativos; ejecuta antes 0002_catalogo_permisos.")
        if not codigos:
            raise CommandError("El catálogo de permisos está vacío.")

        if empresa:
            rol_existente = Rol.objects.filter(empresa=empresa, codigo=ADMIN_CODE).first()
            if rol_existente and (not rol_existente.activo or not rol_existente.protegido):
                raise CommandError("Ya existe un rol administrador incompatible; revisar manualmente.")
            if rol_existente:
                actuales = set(rol_existente.permisos_asignados.values_list("permiso__codigo", flat=True))
                if actuales != codigos:
                    raise CommandError("El rol administrador existente no coincide con el catálogo. No se modificará implícitamente.")

        self.stdout.write("=== VISTA PREVIA bootstrap_tocal ===")
        self.stdout.write(f"Usuario: {usuario.username} (id={usuario.pk})")
        self.stdout.write(f"Empresa: {empresa.nombre if empresa else options['empresa_nombre']} ({empresa.pk if empresa else 'NUEVA'})")
        self.stdout.write(f"Rol: {ADMIN_CODE} | permisos activos: {len(codigos)}")
        self.stdout.write(f"Obras explícitas para vincular: {', '.join(str(o.pk) for o in obras) or 'ninguna'}")
        self.stdout.write("Sin cambios en User.rol, ObraUsuario o API antigua.")
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Vista previa solamente. Agrega --apply --confirmar BOOTSTRAP para ejecutar."))
            return

        with transaction.atomic():
            if empresa is None:
                empresa = Empresa.objects.create(nombre=nombre, rut=rut)
            else:
                empresa = Empresa.objects.select_for_update().get(pk=empresa.pk)
                if not empresa.activa:
                    raise CommandError("La empresa fue desactivada durante la operación.")
            rol, nuevo_rol = Rol.objects.get_or_create(
                empresa=empresa, codigo=ADMIN_CODE,
                defaults={"nombre": "Administrador general", "descripcion": "Rol inicial protegido", "activo": True, "protegido": True},
            )
            if not rol.activo or not rol.protegido:
                raise CommandError("Rol administrador incompatible.")
            existentes = set(rol.permisos_asignados.values_list("permiso__codigo", flat=True))
            if nuevo_rol:
                RolPermiso.objects.bulk_create([RolPermiso(rol=rol, permiso=p) for p in Permiso.objects.filter(activo=True)])
            elif existentes != codigos:
                raise CommandError("Rol existente alterado: no se modificará implícitamente.")
            membresia, _ = MembresiaEmpresa.objects.get_or_create(
                empresa=empresa, usuario=usuario, defaults={"activa": True},
            )
            if not membresia.activa:
                membresia.activa = True
                membresia.save(update_fields=["activa"])
            asignacion, _ = AsignacionRol.objects.get_or_create(
                membresia=membresia, rol=rol, empresa_obra=None,
                defaults={"activa": True},
            )
            if not asignacion.activa:
                asignacion.activa = True
                asignacion.save(update_fields=["activa"])
            for obra in obras:
                EmpresaObra.objects.get_or_create(obra=obra, defaults={"empresa": empresa})
            RegistroAuditoria.objects.create(
                empresa=empresa, actor=usuario, accion="bootstrap.administrador",
                entidad="Empresa", entidad_id=str(empresa.pk),
                detalle={"rol_id": str(rol.pk), "obras_vinculadas": [str(o.pk) for o in obras]},
            )
        self.stdout.write(self.style.SUCCESS(f"Bootstrap aplicado. empresa_id={empresa.pk} administrador={usuario.username}"))
