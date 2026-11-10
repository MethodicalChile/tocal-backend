import json
from django.test import TestCase
from django.urls import reverse
from intranet.models import User
from apps.authorization.models import Empresa, MembresiaEmpresa, Rol, Permiso, RolPermiso, AsignacionRol


class CreateUserAPITests(TestCase):
    def setUp(self):
        self.company = Empresa.objects.create(nombre='Empresa A')
        self.other = Empresa.objects.create(nombre='Empresa B')
        self.admin = User.objects.create_user(username='admin-create', email='admin-create@example.com', password='Secure-Test-1234')
        member = MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.admin)
        role = Rol.objects.create(empresa=self.company, codigo='admin', nombre='Admin')
        perm, _ = Permiso.objects.get_or_create(codigo='roles.administrar', defaults={
            'modulo':'roles', 'accion':'administrar', 'nombre':'Administrar roles'})
        RolPermiso.objects.create(rol=role, permiso=perm)
        AsignacionRol.objects.create(membresia=member, rol=role)
        self.url = reverse('auth-member-create-user', kwargs={'empresa_id': self.company.pk})
        self.client.force_login(self.admin)

    def post(self, data, url=None):
        return self.client.post(url or self.url, json.dumps(data), content_type='application/json')

    def test_create_user_creates_membership_without_role(self):
        res = self.post({'nombre': 'Prevencionista', 'email': 'prev@example.com', 'password': 'Secure-Test-1234'})
        self.assertEqual(res.status_code, 201, res.content)
        user = User.objects.get(email='prev@example.com')
        self.assertTrue(user.check_password('Secure-Test-1234'))
        self.assertEqual(user.rol, 'lectura')
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(MembresiaEmpresa.objects.filter(empresa=self.company, usuario=user).exists())
        self.assertFalse(AsignacionRol.objects.filter(membresia__usuario=user).exists())

    def test_duplicate_email_not_created(self):
        body = {'nombre':'Prev', 'email':'PREV@example.com', 'password':'Secure-Test-1234'}
        self.assertEqual(self.post(body).status_code, 201)
        self.assertEqual(self.post(body).status_code, 409)

    def test_other_company_forbidden(self):
        url = reverse('auth-member-create-user', kwargs={'empresa_id': self.other.pk})
        response = self.post({'nombre':'Prev', 'email':'other@example.com', 'password':'Secure-Test-1234'}, url)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='other@example.com').exists())

    def test_non_admin_cannot_create(self):
        user = User.objects.create_user(username='limited', email='limited@example.com', password='Secure-Test-1234')
        self.client.force_login(user)
        response = self.post({'nombre':'Prev', 'email':'no@example.com', 'password':'Secure-Test-1234'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='no@example.com').exists())
