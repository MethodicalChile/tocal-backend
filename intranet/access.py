from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Obra, ObraUsuario

MODULES = [
    ("resumen", "Resumen"),
    ("pdr", "Prevención"),
    ("avance", "Avance"),
    ("edp", "Estados de pago"),
    ("adicionales", "Adicionales"),
    ("rdi", "RDI"),
    ("fotos", "Fotografías"),
    ("informes", "Informes"),
]

# El experto PDR puede consultar otros módulos por URL; aquí se muestran los de su trabajo.
PDR_MODULES = ("pdr", "fotos")


def visible_modules(user):
    if user.rol == "experto_pdr":
        return [(slug, label) for slug, label in MODULES if slug in PDR_MODULES]
    return MODULES


def visible_obras(user):
    qs = Obra.objects.order_by("nombre")
    if user.rol != "gerencia":
        qs = qs.filter(pk__in=ObraUsuario.objects.filter(user=user).values("obra_id"))
    return qs


def get_obra(user, obra_id):
    return get_object_or_404(visible_obras(user), pk=obra_id)


def can_edit(user, module):
    if module == "ventas":
        return user.rol == "gerencia"
    return user.rol in ("gerencia", "admin_obra") or (
        user.rol == "experto_pdr" and module in ("pdr", "fotos")
    )


def require_editor(user, module):
    if not can_edit(user, module):
        raise PermissionDenied("No tienes permiso para editar este módulo.")
