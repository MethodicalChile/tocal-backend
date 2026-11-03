"""Acceso a obras: compatibilidad legacy para usuarios aún sin membresía RBAC.

Cuando existe cualquier membresía RBAC (incluso inactiva), la visibilidad
se obtiene exclusivamente de las asignaciones activas y los permisos nuevos.
No utiliza is_superuser como acceso implícito.
"""
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db.models import F, Q

from .models import Obra, ObraUsuario

MODULES = [
    ("resumen", "Resumen"), ("pdr", "Prevención"),
    ("avance", "Avance"), ("edp", "Estados de pago"),
    ("adicionales", "Adicionales"), ("rdi", "RDI"),
    ("fotos", "Fotografías"), ("informes", "Informes"),
]
PDR_MODULES = ("pdr", "fotos")


def uses_rbac(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    from apps.authorization.models import MembresiaEmpresa
    # Incluye membresías inactivas para impedir retroceso accidental a legacy.
    return MembresiaEmpresa.objects.filter(usuario=user).exists()


def visible_modules(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return []
    if not uses_rbac(user) and user.rol == "experto_pdr":
        return [(slug, label) for slug, label in MODULES if slug in PDR_MODULES]
    if uses_rbac(user):
        from apps.authorization.models import EmpresaObra
        from apps.authorization.permissions import has_permission
        obras = list(visible_obras(user).values_list('pk', flat=True))
        vinculos = list(EmpresaObra.objects.filter(obra_id__in=obras).values_list('empresa_id', 'obra_id'))
        return [(slug, label) for slug, label in MODULES
                if any(has_permission(user=user, permission=f'{slug}.ver', empresa_id=empresa_id, obra_id=obra_id)
                       for empresa_id, obra_id in vinculos)]
    return MODULES


def visible_obras(user):
    base = Obra.objects.order_by('nombre')
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return base.none()
    if not uses_rbac(user):
        if user.rol != 'gerencia':
            base = base.filter(pk__in=ObraUsuario.objects.filter(user=user).values('obra_id'))
        return base

    from apps.authorization.models import AsignacionRol, EmpresaObra
    # No basta con ser miembro; se requiere un rol activo con permiso obras.ver.
    assignments = AsignacionRol.objects.filter(
        membresia__usuario=user,
        membresia__activa=True,
        membresia__empresa__activa=True,
        activa=True,
        rol__activo=True,
        rol__empresa_id=F('membresia__empresa_id'),
        rol__permisos_asignados__permiso__codigo='obras.ver',
        rol__permisos_asignados__permiso__activo=True,
    )
    global_companies = assignments.filter(empresa_obra__isnull=True).values('membresia__empresa_id')
    scoped_links = assignments.filter(empresa_obra__isnull=False, empresa_obra__empresa_id=F('membresia__empresa_id')).values('empresa_obra_id')
    return base.filter(pk__in=EmpresaObra.objects.filter(
        Q(empresa_id__in=global_companies) | Q(pk__in=scoped_links),
        empresa__activa=True,
    ).values('obra_id')).distinct()


def get_obra(user, obra_id):
    return get_object_or_404(visible_obras(user), pk=obra_id)


# Acciones disponibles en el catálogo 0002_catalogo_permisos.
# No inferir permisos nuevos ni tratar todos los métodos como editar.
WRITE_ACTIONS = {
    'pdr': {'create': 'pdr.editar', 'edit': 'pdr.editar', 'delete': 'pdr.editar'},
    'avance': {'create': 'avance.editar', 'edit': 'avance.editar', 'delete': 'avance.editar'},
    'edp': {'create': 'edp.editar', 'edit': 'edp.editar', 'delete': 'edp.editar'},
    'adicionales': {'create': 'adicionales.editar', 'edit': 'adicionales.editar', 'delete': 'adicionales.editar'},
    'rdi': {'create': 'rdi.editar', 'edit': 'rdi.editar', 'delete': 'rdi.editar'},
    'fotos': {'create': 'fotos.crear', 'edit': None, 'delete': 'fotos.eliminar'},
    'informes': {'create': 'informes.crear', 'edit': 'informes.editar', 'delete': 'informes.eliminar', 'approve': 'informes.aprobar', 'download': 'informes.descargar'},
}


def _rbac_permission(user, module, obra, action):
    from apps.authorization.models import EmpresaObra
    from apps.authorization.permissions import has_permission
    codigo = f'{module}.ver' if action == 'view' else WRITE_ACTIONS.get(module, {}).get(action)
    if not codigo or obra is None:
        return False
    # EmpresaObra.obra es OneToOne: una obra solo puede pertenecer a una
    # empresa. No seleccionar una empresa arbitraria ni permitir obras huérfanas.
    empresa_id = EmpresaObra.objects.filter(
        obra=obra, empresa__activa=True
    ).values_list('empresa_id', flat=True).first()
    return bool(empresa_id and has_permission(
        user=user, permission=codigo, empresa_id=empresa_id, obra_id=obra.pk
    ))


def _legacy_can_access_obra(user, obra):
    if obra is None:
        return False
    if user.rol == 'gerencia':
        return True
    return ObraUsuario.objects.filter(user=user, obra_id=obra.pk).exists()


def can_view(user, module, obra):
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if uses_rbac(user):
        return _rbac_permission(user, module, obra, 'view')
    if not _legacy_can_access_obra(user, obra):
        return False
    return user.rol != 'experto_pdr' or module in PDR_MODULES


def require_viewer(user, module, obra):
    if not can_view(user, module, obra):
        raise PermissionDenied('No tienes permiso para consultar este módulo.')


def can_edit(user, module, obra=None, action='edit'):
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if uses_rbac(user):
        return _rbac_permission(user, module, obra, action)
    if module == 'ventas':
        return user.rol == 'gerencia'
    # Compatibilidad para algunos tests y consumidores internos que no entregan
    # obra, pero nunca validar una operación concreta sobre otra obra.
    if obra is not None and not _legacy_can_access_obra(user, obra):
        return False
    return user.rol in ('gerencia', 'admin_obra') or (
        user.rol == 'experto_pdr' and module in ('pdr', 'fotos')
    )


def require_editor(user, module, obra=None, action='edit'):
    if not can_edit(user, module, obra=obra, action=action):
        raise PermissionDenied('No tienes permiso para esta operación.')
