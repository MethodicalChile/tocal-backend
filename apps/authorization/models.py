"""Estructura multiempresa y roles/acciones con ámbitos de aplicación.

No modifica intranet.User.rol ni intranet.ObraUsuario: su autorización
actual continúa operativa hasta que se integre explícitamente esta app.
"""

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class BaseRegistro(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Empresa(BaseRegistro):
    nombre = models.CharField(max_length=200)
    rut = models.CharField(max_length=20, unique=True, null=True, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "tocal_auth_empresas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class EmpresaObra(BaseRegistro):
    """Una obra pertenece a una sola empresa en un momento dado.

    Las obras existentes permanecen SIN asociar hasta su validación manual.
    """

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="obras_vinculadas"
    )
    obra = models.OneToOneField(
        "intranet.Obra", on_delete=models.PROTECT, related_name="vinculo_empresa"
    )

    class Meta:
        db_table = "tocal_auth_empresa_obras"
        ordering = ["creado_en"]

    def __str__(self):
        return f"{self.empresa} - {self.obra}"


class MembresiaEmpresa(BaseRegistro):
    """El usuario está habilitado para actuar dentro de esta empresa."""

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="membresias"
    )
    usuario = models.ForeignKey(
        "intranet.User", on_delete=models.PROTECT, related_name="membresias_empresas"
    )
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "tocal_auth_membresias"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "usuario"], name="auth_membresia_empresa_usuario_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.usuario} en {self.empresa}"


class Permiso(BaseRegistro):
    """Catálogo técnico. Las empresas gestionan RolPermiso, no códigos arbitrarios."""

    codigo = models.CharField(max_length=100, unique=True)
    modulo = models.CharField(max_length=50)
    accion = models.CharField(max_length=50)
    nombre = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "tocal_auth_permisos"
        ordering = ["modulo", "accion"]

    def clean(self):
        super().clean()
        if self.modulo and self.accion and self.codigo != f"{self.modulo}.{self.accion}":
            raise ValidationError({"codigo": "Debe ser 'modulo.accion'."})

    def __str__(self):
        return self.codigo


class Rol(BaseRegistro):
    """Los roles son propios de cada empresa, nunca compartidos entre tenants."""

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="roles"
    )
    codigo = models.SlugField(max_length=64)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    protegido = models.BooleanField(default=False)

    class Meta:
        db_table = "tocal_auth_roles"
        ordering = ["empresa", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"], name="auth_rol_empresa_codigo_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.empresa}: {self.nombre}"


class RolPermiso(BaseRegistro):
    rol = models.ForeignKey(
        Rol, on_delete=models.CASCADE, related_name="permisos_asignados"
    )
    permiso = models.ForeignKey(
        Permiso, on_delete=models.PROTECT, related_name="roles_asignados"
    )

    class Meta:
        db_table = "tocal_auth_rol_permisos"
        constraints = [
            models.UniqueConstraint(
                fields=["rol", "permiso"], name="auth_rol_permiso_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.rol} -> {self.permiso}"


class AsignacionRol(BaseRegistro):
    """empresa_obra=NULL: rol para toda la empresa; con valor: solo esa obra.

    La membresía, el rol y la obra deben pertenecer a la misma empresa.
    """

    membresia = models.ForeignKey(
        MembresiaEmpresa, on_delete=models.PROTECT, related_name="asignaciones"
    )
    rol = models.ForeignKey(
        Rol, on_delete=models.PROTECT, related_name="asignaciones"
    )
    empresa_obra = models.ForeignKey(
        EmpresaObra,
        on_delete=models.PROTECT,
        related_name="asignaciones_roles",
        null=True,
        blank=True,
    )
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "tocal_auth_asignaciones"
        constraints = [
            models.UniqueConstraint(
                fields=["membresia", "rol"],
                condition=Q(empresa_obra__isnull=True),
                name="auth_asig_rol_empresa_uniq",
            ),
            models.UniqueConstraint(
                fields=["membresia", "rol", "empresa_obra"],
                condition=Q(empresa_obra__isnull=False),
                name="auth_asig_rol_obra_uniq",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.membresia_id or not self.rol_id:
            return
        empresa_id = self.membresia.empresa_id
        errors = {}
        if self.rol.empresa_id != empresa_id:
            errors["rol"] = "El rol no pertenece a la empresa de la membresía."
        if self.empresa_obra_id and self.empresa_obra.empresa_id != empresa_id:
            errors["empresa_obra"] = "La obra pertenece a otra empresa."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Evita asignaciones cruzadas mediante .save(), Admin o API normal.
        # bulk_create(), update() y SQL directo omiten este control: no usarlos
        # para gestionar asignaciones; la API debe verificar el ámbito también.
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        ambito = self.empresa_obra.obra_id if self.empresa_obra_id else "empresa"
        return f"{self.membresia} -> {self.rol.codigo} ({ambito})"


class RegistroAuditoria(BaseRegistro):
    """Bitácora; no persistir contraseñas, tokens ni contenido médico en detalle."""

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="auditorias"
    )
    actor = models.ForeignKey(
        "intranet.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="auditorias_realizadas"
    )
    accion = models.CharField(max_length=120)
    entidad = models.CharField(max_length=120)
    entidad_id = models.CharField(max_length=64)
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "tocal_auth_auditoria"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.accion} {self.entidad}:{self.entidad_id}"
