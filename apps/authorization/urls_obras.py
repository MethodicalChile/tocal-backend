from django.urls import path
from .views_obras import company_works

urlpatterns = [
    path('empresas/<uuid:empresa_id>/obras/', company_works, name='auth-company-works'),
]
