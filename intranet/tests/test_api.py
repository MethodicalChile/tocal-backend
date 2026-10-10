"""Pruebas iniciales de autenticación y autorización JSON.
Ejecutar: python manage.py test intranet.tests.test_api
"""
import json
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Obra

class TocalApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa@tocal.cl', email='qa@tocal.cl',
                    password='Test-Seguro-2026!', name='QA', rol='lectura')
        self.obra = Obra.objects.create(nombre='Obra API', razon_social='Tocal', rut='11111111-1',
                    servicio='Construcción', inicio_contrato='2026-01-01')

    def test_csrf_publico(self):
        r = self.client.get('/api/csrf')
        self.assertEqual(r.status_code, 200)
        self.assertIn('csrfToken', r.json())

    def test_sesion_protegida(self):
        r = self.client.get('/api/session')
        self.assertEqual(r.status_code, 401)

    def test_login_logout(self):
        r = self.client.post('/api/auth/login', data=json.dumps({
            'email': 'qa@tocal.cl', 'password': 'Test-Seguro-2026!'}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get('/api/session').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout', data='{}', content_type='application/json').status_code, 200)
        self.assertEqual(self.client.get('/api/session').status_code, 401)

    def test_no_ver_obra_no_asignada(self):
        self.client.force_login(self.user)
        r = self.client.get(f'/api/obras/{self.obra.pk}/resumen')
        self.assertEqual(r.status_code, 404)

    def test_no_ventas_no_gerencia(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/ventas').status_code, 403)
