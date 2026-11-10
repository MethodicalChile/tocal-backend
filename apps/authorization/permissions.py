from uuid import UUID

from django.db.models import F, Q

from .models import (
    AsignacionRol,
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
)


def _valid_uuid(value):
    """Valida identificadores UUID utilizados por Empresa."""
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _get_empresa(empresa_id):
    """Obtiene una empresa activa o None."""
    empresa_uuid = _valid_uuid(empresa_id)

    if empresa_uuid is None:
        return None

    return Empresa.objects.filter(
        pk=empresa_uuid,
        activa=True,
    ).first()


def _get_vinculo(empresa, obra_id):
    """Obtiene el vínculo entre la empresa y la obra solicitada.

    obra_id identifica a intranet.Obra y puede llegar como
    cadena de texto.

    Nunca se busca una obra fuera de la empresa indicada.
    """
    if obra_id is None:
        return None

    obra_id = str(obra_id).strip()

    if not obra_id or len(obra_id) > 64:
        return None

    return EmpresaObra.objects.filter(
        empresa=empresa,
        obra_id=obra_id,
    ).first()


def _asignaciones_validas(user, empresa):
    """Obtiene asignaciones RBAC activas y coherentes."""

    return (
        AsignacionRol.objects
        .filter(
            membresia__usuario=user,
            membresia__empresa=empresa,
            membresia__activa=True,
            activa=True,
            rol__activo=True,
            rol__empresa=empresa,
        )
        .filter(
            Q(empresa_obra__isnull=True)
            | Q(
                empresa_obra__empresa_id=F(
                    "membresia__empresa_id"
                )
            )
        )
    )


def _filtrar_ambito(asignaciones, vinculo):
    """Limita los roles al ámbito empresarial o de obra."""

    if vinculo is None:
        return asignaciones.filter(
            empresa_obra__isnull=True,
        )

    return asignaciones.filter(
        Q(empresa_obra__isnull=True)
        | Q(empresa_obra=vinculo)
    )


def has_permission(
    *,
    user,
    permission: str,
    empresa_id,
    obra_id=None,
) -> bool:
    """Comprueba un permiso en una empresa u obra."""

    # 1. Validar usuario
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
    ):
        return False

    # 2. Validar código del permiso
    if (
        not isinstance(permission, str)
        or not permission.strip()
    ):
        return False

    # 3. Validar empresa
    empresa = _get_empresa(empresa_id)

    if empresa is None:
        return False

    # 4. Validar obra y relación empresarial
    vinculo = None

    if obra_id is not None:
        vinculo = _get_vinculo(empresa, obra_id)

        if vinculo is None:
            return False

    # 5. Obtener asignaciones válidas
    asignaciones = _asignaciones_validas(
        user,
        empresa,
    )

    # 6. Limitar ámbito
    asignaciones = _filtrar_ambito(
        asignaciones,
        vinculo,
    )

    # 7. Verificar permiso activo
    return asignaciones.filter(
        rol__permisos_asignados__permiso__codigo=permission,
        rol__permisos_asignados__permiso__activo=True,
    ).exists()


def effective_permissions(
    *,
    user,
    empresa_id,
    obra_id=None,
) -> set[str]:
    """Devuelve los códigos de permisos autorizados.

    Aplica las mismas reglas de aislamiento que has_permission.
    """

    # 1. Validar usuario
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
    ):
        return set()

    # 2. Validar empresa
    empresa = _get_empresa(empresa_id)

    if empresa is None:
        return set()

    # 3. Validar obra
    vinculo = None

    if obra_id is not None:
        vinculo = _get_vinculo(empresa, obra_id)

        if vinculo is None:
            return set()

    # 4. Obtener asignaciones válidas
    asignaciones = _asignaciones_validas(
        user,
        empresa,
    )

    # 5. Limitar ámbito
    asignaciones = _filtrar_ambito(
        asignaciones,
        vinculo,
    )

    # 6. Recuperar permisos activos
    permisos = asignaciones.filter(
        rol__permisos_asignados__permiso__activo=True,
    ).values_list(
        "rol__permisos_asignados__permiso__codigo",
        flat=True,
    )

    return set(permisos)


def authorized_obra_ids(
    *,
    user,
    permission: str,
    empresa_id,
) -> set[str] | None:
    """Devuelve None si el usuario posee el permiso a nivel global de empresa,
    o el conjunto de obra_id autorizados dentro de la empresa para ese permiso.
    Si no tiene acceso en ningún ámbito, devuelve set().
    """
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or not isinstance(permission, str)
        or not permission.strip()
    ):
        return set()

    empresa = _get_empresa(empresa_id)
    if empresa is None:
        return set()

    asignaciones = _asignaciones_validas(user, empresa).filter(
        rol__permisos_asignados__permiso__codigo=permission,
        rol__permisos_asignados__permiso__activo=True,
    )
    if asignaciones.filter(empresa_obra__isnull=True).exists():
        return None

    return set(
        asignaciones.filter(empresa_obra__isnull=False)
        .values_list("empresa_obra__obra_id", flat=True)
    )


def has_any_obra_permission(
    *,
    user,
    permission: str,
    empresa_id,
    obra_ids=None,
) -> bool:
    """Comprueba si el usuario tiene el permiso a nivel empresa o en al menos
    una obra vinculada a la empresa (o dentro de `obra_ids` si se especifica).
    """
    scope = authorized_obra_ids(
        user=user,
        permission=permission,
        empresa_id=empresa_id,
    )
    if scope is None:
        return True
    if not scope:
        return False
    if obra_ids is None:
        return True
    target = {str(oid) for oid in obra_ids if oid is not None}
    return bool(scope & target)


def all_company_permissions(
    *,
    user,
    empresa_id,
) -> dict:
    """Devuelve permisos globales de empresa, mapa de permisos por obra y unión."""
    if not user or not user.is_authenticated or not user.is_active:
        return {"permissions": [], "global_permissions": [], "obra_permissions": {}}

    empresa = _get_empresa(empresa_id)
    if empresa is None:
        return {"permissions": [], "global_permissions": [], "obra_permissions": {}}

    asignaciones = (
        _asignaciones_validas(user, empresa)
        .filter(rol__permisos_asignados__permiso__activo=True)
        .values_list(
            "empresa_obra__obra_id",
            "rol__permisos_asignados__permiso__codigo",
        )
    )
    global_perms: set[str] = set()
    obra_perms: dict[str, set[str]] = {}
    union_perms: set[str] = set()

    for obra_id, codigo in asignaciones:
        if not codigo:
            continue
        union_perms.add(codigo)
        if obra_id is None:
            global_perms.add(codigo)
        else:
            obra_perms.setdefault(obra_id, set()).add(codigo)

    return {
        "permissions": sorted(union_perms),
        "global_permissions": sorted(global_perms),
        "obra_permissions": {
            oid: sorted( codes | global_perms )
            for oid, codes in sorted(obra_perms.items())
        },
    }

