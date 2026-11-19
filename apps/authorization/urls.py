from django.urls import path
from . import views
from .views_companies import my_companies, company_create, company_detail
from .urls_assignments import urlpatterns as assignment_patterns
from .urls_obras import urlpatterns as obras_patterns

urlpatterns = [
    path('mis-empresas/', my_companies, name='auth-my-companies'),
    path('empresas/crear/', company_create, name='auth-company-create'),
    path('empresas/<uuid:empresa_id>/', company_detail, name='auth-company-detail'),
    path('empresas/<uuid:empresa_id>/roles/', views.roles_list, name='auth-roles-list'),
    path('empresas/<uuid:empresa_id>/roles/crear/', views.roles_create, name='auth-roles-create'),
    path('empresas/<uuid:empresa_id>/roles/<uuid:rol_id>/permisos/', views.role_permissions_replace, name='auth-role-permissions'),
    path('empresas/<uuid:empresa_id>/permisos/', views.permissions_list, name='auth-permissions-list'),
    path('empresas/<uuid:empresa_id>/mis-permisos/', views.my_permissions, name='auth-my-permissions'),
    path('empresas/<uuid:empresa_id>/auditoria/', views.audit_logs_list, name='auth-audit-list'),
]

urlpatterns += assignment_patterns
urlpatterns += obras_patterns
