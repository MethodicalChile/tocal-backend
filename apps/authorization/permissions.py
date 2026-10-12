"""Evaluación de permisos nuevos: nunca utiliza User.rol ni is_superuser.

La obra es siempre un ID de intranet.Obra (no el ID de EmpresaObra).
Si obra_id=None se exige una asignación a nivel de empresa.
"""
from django.db.models import Q

from .models import AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa, Permiso


def has_permission(*, user, permission: str, empresa_id, obra_id=None) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if not empresa_id or not permission or not isinstance(permission, str):
        return False
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return False

    vinculo = None
    if obra_id is not None:
        vinculo = EmpresaObra.objects.filter(empresa_id=empresa_id, obra_id=obra_id).first()
        if vinculo is None:
            return False

    membresias = MembresiaEmpresa.objects.filter(
        empresa_id=empresa_id, usuario=user, activa=True
    )
    if not membresias.exists():
        return False

    asignaciones = AsignacionRol.objects.filter(
        membresia__in=membresias,
        activa=True,
        rol__activo=True,
        rol__empresa_id=empresa_id,
        rol__permisos_asignados__permiso__codigo=permission,
        rol__permisos_asignados__permiso__activo=True,
    )
    if vinculo is None:
        asignaciones = asignaciones.filter(empresa_obra__isnull=True)
    else:
        asignaciones = asignaciones.filter(
            Q(empresa_obra__isnull=True) | Q(empresa_obra=vinculo)
        )
    return asignaciones.exists()


def effective_permissions(*, user, empresa_id, obra_id=None) -> set[str]:
    """Retorna códigos autorizados. Mismo aislamiento que has_permission."""
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    if not Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        return set()
    vinculo = None
    if obra_id is not None:
        vinculo = EmpresaObra.objects.filter(empresa_id=empresa_id, obra_id=obra_id).first()
        if vinculo is None:
            return set()
    qs = AsignacionRol.objects.filter(
        membresia__usuario=user,
        membresia__empresa_id=empresa_id,
        membresia__activa=True,
        activa=True,
        rol__activo=True,
        rol__empresa_id=empresa_id,
        rol__permisos_asignados__permiso__activo=True,
    )
    if vinculo is None:
        qs = qs.filter(empresa_obra__isnull=True)
    else:
        qs = qs.filter(Q(empresa_obra__isnull=True) | Q(empresa_obra=vinculo))
    return set(qs.values_list("rol__permisos_asignados__permiso__codigo", flat=True))
