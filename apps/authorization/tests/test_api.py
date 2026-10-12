"""Pruebas básicas para los endpoints administrativos de la fase controlada."""
import json
from django.test import TestCase
from django.urls import reverse
from intranet.models import User
from apps.authorization.models import Empresa, MembresiaEmpresa, Permiso, Rol, RolPermiso, AsignacionRol


class AuthorizationAPITests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre='Empresa test')
        self.otra = Empresa.objects.create(nombre='Otra empresa')
        self.usuario = User.objects.create_user(username='owner-test', password='Temporary-test-12345')
        membresia = MembresiaEmpresa.objects.create(empresa=self.empresa, usuario=self.usuario)
        self.admin_role = Rol.objects.create(empresa=self.empresa, codigo='admin', nombre='Administrador')
        for code in ('roles.ver', 'roles.administrar', 'empleados.ver'):
            permission, _ = Permiso.objects.get_or_create(codigo=code, defaults={'modulo':code.split('.')[0], 'accion':code.split('.')[1], 'nombre':code})
            RolPermiso.objects.create(rol=self.admin_role, permiso=permission)
        AsignacionRol.objects.create(membresia=membresia, rol=self.admin_role)
        self.client.force_login(self.usuario)

    def test_company_isolation(self):
        url = reverse('auth-roles-list', kwargs={'empresa_id':self.otra.pk})
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_roles_listing_and_creation(self):
        base = {'empresa_id':self.empresa.pk}
        response = self.client.get(reverse('auth-roles-list', kwargs=base))
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('auth-roles-create', kwargs=base), data=json.dumps({'codigo':'jefe','nombre':'Jefe'}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        role_id = response.json()['id']
        url = reverse('auth-role-permissions', kwargs={**base, 'rol_id':role_id})
        response = self.client.put(url, data=json.dumps({'permisos':['empleados.ver']}), content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_permission_escalation_rejected(self):
        role = Rol.objects.create(empresa=self.empresa, codigo='jefe', nombre='Jefe')
        url = reverse('auth-role-permissions', kwargs={'empresa_id':self.empresa.pk, 'rol_id':role.pk})
        response = self.client.put(url, data=json.dumps({'permisos':['usuarios.administrar']}), content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_assigned_role_cannot_be_reconfigured(self):
        url = reverse('auth-role-permissions', kwargs={'empresa_id':self.empresa.pk, 'rol_id':self.admin_role.pk})
        response = self.client.put(url, data=json.dumps({'permisos':[]}), content_type='application/json')
        self.assertEqual(response.status_code, 409)
