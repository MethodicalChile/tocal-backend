from django.urls import path
from . import views, views_extended

# Sin app_name: las rutas existentes se consumen con reverse('documentos-tipos').
urlpatterns = [
    path('empresas/<uuid:empresa_id>/tipos/', views.tipos, name='documentos-tipos'),
    path('empresas/<uuid:empresa_id>/tipos/<uuid:tipo_id>/', views.tipo_detalle, name='documentos-tipo-detalle'),
    path('empresas/<uuid:empresa_id>/requisitos/', views.requisitos, name='documentos-requisitos'),
    path('empresas/<uuid:empresa_id>/requisitos/<uuid:requisito_id>/', views.requisito_detalle, name='documentos-requisito-detalle'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/documentos/', views.documentos_trabajador, name='documentos-trabajador'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/documentos/<uuid:documento_id>/revision/', views.revisar_documento_trabajador, name='documentos-trabajador-revision'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/documentos/<uuid:documento_id>/archivos/', views.archivos_documento_trabajador, name='documentos-trabajador-archivos'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/documentos/<uuid:documento_id>/archivos/<uuid:archivo_id>/descargar/', views.descargar_archivo_documento, name='documentos-trabajador-archivo-descargar'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/cumplimiento/', views.cumplimiento_trabajador, name='documentos-trabajador-cumplimiento'),
    path('empresas/<uuid:empresa_id>/alertas/configuracion/', views.configuracion_alertas, name='documentos-alertas-configuracion'),
    path('empresas/<uuid:empresa_id>/alertas/', views.alertas_vencimiento, name='documentos-alertas'),
    path('empresas/<uuid:empresa_id>/alertas/<uuid:alerta_id>/', views.alerta_vencimiento_detalle, name='documentos-alerta-detalle'),
    # Etapa 7: Documentos de empresa
    path('empresas/<uuid:empresa_id>/documentos-empresa/', views_extended.documentos_empresa, name='documentos-empresa'),
    path('empresas/<uuid:empresa_id>/documentos-empresa/<uuid:documento_id>/revision/', views_extended.revisar_documento_empresa, name='documentos-empresa-revision'),
    path('empresas/<uuid:empresa_id>/documentos-empresa/<uuid:documento_id>/archivos/', views_extended.archivos_documento_empresa, name='documentos-empresa-archivos'),
    path('empresas/<uuid:empresa_id>/documentos-empresa/<uuid:documento_id>/archivos/<uuid:archivo_id>/descargar/', views_extended.descargar_archivo_empresa, name='documentos-empresa-archivo-descargar'),
    path('empresas/<uuid:empresa_id>/cumplimiento-empresa/', views_extended.cumplimiento_empresa, name='documentos-empresa-cumplimiento'),
    # Etapa 8: Equipos y maquinaria
    path('empresas/<uuid:empresa_id>/equipos/', views_extended.equipos, name='documentos-equipos'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/', views_extended.equipo_detalle, name='documentos-equipo-detalle'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/asignaciones/', views_extended.asignaciones_equipo, name='documentos-equipo-asignaciones'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/asignaciones/<uuid:asignacion_id>/', views_extended.asignacion_equipo_detalle, name='documentos-equipo-asignacion-detalle'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/documentos/', views_extended.documentos_equipo, name='documentos-equipo-documentos'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/documentos/<uuid:documento_id>/revision/', views_extended.revisar_documento_equipo, name='documentos-equipo-revision'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/documentos/<uuid:documento_id>/archivos/', views_extended.archivos_documento_equipo, name='documentos-equipo-archivos'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/documentos/<uuid:documento_id>/archivos/<uuid:archivo_id>/descargar/', views_extended.descargar_archivo_equipo, name='documentos-equipo-archivo-descargar'),
    path('empresas/<uuid:empresa_id>/equipos/<uuid:equipo_id>/cumplimiento/', views_extended.cumplimiento_equipo, name='documentos-equipo-cumplimiento'),
    # Etapa 9: Capacitaciones, EPP y habilitación preventiva
    path('empresas/<uuid:empresa_id>/capacitaciones/tipos/', views_extended.tipos_capacitacion, name='documentos-capacitaciones-tipos'),
    path('empresas/<uuid:empresa_id>/capacitaciones/tipos/<uuid:tipo_id>/', views_extended.tipo_capacitacion_detalle, name='documentos-capacitaciones-tipo-detalle'),
    path('empresas/<uuid:empresa_id>/capacitaciones/requisitos/', views_extended.requisitos_capacitacion, name='documentos-capacitaciones-requisitos'),
    path('empresas/<uuid:empresa_id>/capacitaciones/registros/', views_extended.capacitaciones_trabajador, name='documentos-capacitaciones-registros'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/capacitaciones/', views_extended.capacitaciones_trabajador, name='documentos-trabajador-capacitaciones'),
    path('empresas/<uuid:empresa_id>/epp/categorias/', views_extended.categorias_epp, name='documentos-epp-categorias'),
    path('empresas/<uuid:empresa_id>/epp/entregas/', views_extended.entregas_epp, name='documentos-epp-entregas'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/epp/', views_extended.entregas_epp, name='documentos-trabajador-epp'),
    path('empresas/<uuid:empresa_id>/trabajadores/<str:trabajador_id>/habilitacion-preventiva/', views_extended.habilitacion_preventiva, name='documentos-trabajador-habilitacion'),
    # Etapa 10: Dashboard y exportación de cumplimiento
    path('empresas/<uuid:empresa_id>/dashboard-cumplimiento/', views_extended.dashboard_cumplimiento, name='documentos-dashboard-cumplimiento'),
    path('empresas/<uuid:empresa_id>/exportar-cumplimiento/', views_extended.exportar_cumplimiento_csv, name='documentos-exportar-cumplimiento'),
]
