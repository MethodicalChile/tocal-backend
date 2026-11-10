from django.urls import path
from .views_obras import company_works, company_work_detail

urlpatterns = [
    path('empresas/<uuid:empresa_id>/obras/', company_works, name='auth-company-works'),
    path('empresas/<uuid:empresa_id>/obras/<str:obra_id>/', company_work_detail, name='auth-company-work-detail'),
]
