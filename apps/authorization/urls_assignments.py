from django.urls import path
from . import views_assignments as views

urlpatterns = [
    path('empresas/<uuid:empresa_id>/miembros/', views.members_list, name='auth-members-list'),
    path('empresas/<uuid:empresa_id>/miembros/crear/', views.member_add, name='auth-member-add'),
    path('empresas/<uuid:empresa_id>/asignaciones/', views.assignments_list, name='auth-assignments-list'),
    path('empresas/<uuid:empresa_id>/asignaciones/crear/', views.assignment_add, name='auth-assignment-add'),
    path('empresas/<uuid:empresa_id>/asignaciones/<uuid:assignment_id>/revocar/', views.assignment_revoke, name='auth-assignment-revoke'),
]
