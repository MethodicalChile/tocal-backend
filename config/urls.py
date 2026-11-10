from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Administración Django
    path(
        "admin/",
        admin.site.urls,
    ),

    # APIs actuales de Tocal
    path(
        "api/",
        include("intranet.rest_urls"),
    ),

    # Empresas, roles y permisos RBAC
    path(
        "api/authorization/",
        include("apps.authorization.urls"),
    ),

    # Gestión documental (habilitar cuando exista el módulo)
    path("api/documentos/", include("apps.documents.urls")),
]