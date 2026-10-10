from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.User)
class TocalUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Intranet", {"fields": ("name", "rol")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Intranet", {"fields": ("email", "name", "rol")}),)
    list_display = ("email", "name", "rol", "is_active")


# Solo los usuarios técnicos creados explícitamente pueden entrar al administrador.
for model in (models.Obra, models.ObraUsuario, models.ChecklistItem, models.Semana, models.Curva):
    admin.site.register(model)
admin.site.site_header = "Administración Tocal"


@admin.register(models.SolicitudPrivacidad)
class SolicitudPrivacidadAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "tipo", "estado", "created_at", "closed_at")
    list_filter = ("tipo", "estado")
    search_fields = ("usuario__email", "id")
    readonly_fields = ("id", "usuario", "tipo", "detalle", "created_at")
    # Solo personal técnico con acceso al Admin de Django y permiso del modelo.
