from django.urls import path
from . import views
from .urls_assignments import urlpatterns as assignment_patterns
from .urls_obras import urlpatterns as obras_patterns

urlpatterns = [
    path('empresas/<uuid:empresa_id>/roles/', views.roles_list, name='auth-roles-list'),
    path('empresas/<uuid:empresa_id>/roles/crear/', views.roles_create, name='auth-roles-create'),
    path('empresas/<uuid:empresa_id>/roles/<uuid:rol_id>/permisos/', views.role_permissions_replace, name='auth-role-permissions'),
    path('empresas/<uuid:empresa_id>/permisos/', views.permissions_list, name='auth-permissions-list'),
    path('empresas/<uuid:empresa_id>/mis-permisos/', views.my_permissions, name='auth-my-permissions'),
]

urlpatterns += assignment_patterns
urlpatterns += obras_patterns
