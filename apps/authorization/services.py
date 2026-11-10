"""Operaciones internas seguras. NO publicar directamente como endpoint HTTP.

La futura API deberá verificar además que el actor pueda administrar el rol,
que no conceda permisos superiores a los propios y que no se quede sin admin.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AsignacionRol, EmpresaObra, MembresiaEmpresa, Rol


@transaction.atomic
def assign_role(*, usuario, empresa, rol, obra=None):
    """Crea o reactiva una asignación, solo si existen membresía y ámbito válidos.

    `obra` es una instancia de intranet.Obra, o None para toda la empresa.
    """
    if not empresa.activa or not usuario.is_active or not rol.activo:
        raise ValidationError("Empresa, usuario y rol deben estar activos.")
    if rol.empresa_id != empresa.pk:
        raise ValidationError("El rol pertenece a otra empresa.")
    membresia = MembresiaEmpresa.objects.select_for_update().filter(
        empresa=empresa, usuario=usuario, activa=True
    ).first()
    if membresia is None:
        raise ValidationError("El usuario no tiene una membresía activa en la empresa.")
    vinculo = None
    if obra is not None:
        vinculo = EmpresaObra.objects.filter(empresa=empresa, obra=obra).first()
        if vinculo is None:
            raise ValidationError("La obra no pertenece a esta empresa.")
    asignacion, created = AsignacionRol.objects.get_or_create(
        membresia=membresia, rol=rol, empresa_obra=vinculo,
        defaults={"activa": True},
    )
    # Al reactivar también verificamos integridad del ámbito mediante save/full_clean.
    if not asignacion.activa:
        asignacion.activa = True
        asignacion.save(update_fields=["activa"])
    return asignacion


@transaction.atomic
def revoke_role(*, asignacion):
    """Desactiva sin borrar trazabilidad. Solo para uso interno controlado."""
    locked = AsignacionRol.objects.select_for_update().get(pk=asignacion.pk)
    locked.activa = False
    locked.save(update_fields=["activa"])
    return locked
