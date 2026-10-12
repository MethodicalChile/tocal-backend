import json
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Obra
from apps.authorization.models import (Empresa, MembresiaEmpresa, Permiso, Rol,
                                        RolPermiso, AsignacionRol)


class AssignmentAPITests(TestCase):
    def setUp(self):
        self.company = Empresa.objects.create(
            nombre='Tocal Test'
        )

        self.other = Empresa.objects.create(
            nombre='Ajena'
        )

        self.admin = User.objects.create_user(
            username='p4-admin',
            email='p4-admin@example.com',
            password='Secure-Test-1234'
        )

        self.employee = User.objects.create_user(
            username='p4-employee',
            email='p4-employee@example.com',
            password='Secure-Test-1234'
        )

        admin_member = MembresiaEmpresa.objects.create(
            empresa=self.company,
            usuario=self.admin
        )

        self.role = Rol.objects.create(
            empresa=self.company,
            codigo='admin',
            nombre='Admin'
        )

        for code in (
            'roles.administrar',
            'roles.ver',
            'empleados.ver'
        ):
            module, action = code.split('.')

            permission, _ = Permiso.objects.get_or_create(
                codigo=code,
                defaults={
                    'modulo': module,
                    'accion': action,
                    'nombre': code
                }
            )

            RolPermiso.objects.create(
                rol=self.role,
                permiso=permission
            )

        self.admin_assignment = AsignacionRol.objects.create(
            membresia=admin_member,
            rol=self.role
        )

        self.client.force_login(self.admin)

    def test_add_member_and_assign_role(self):
        root = {'empresa_id': self.company.pk}
        resp = self.client.post(reverse('auth-member-add', kwargs=root),
                                json.dumps({'usuario_id': self.employee.pk}), content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        resp = self.client.post(reverse('auth-assignment-add', kwargs=root),
                                json.dumps({'usuario_id': self.employee.pk,
                                            'rol_id': str(self.role.pk)}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AsignacionRol.objects.filter(membresia__usuario=self.employee, activa=True).exists())

    def test_cannot_revoke_last_admin(self):
        resp = self.client.post(reverse('auth-assignment-revoke', kwargs={
            'empresa_id': self.company.pk, 'assignment_id': self.admin_assignment.pk}),
            '{}', content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.admin_assignment.refresh_from_db()
        self.assertTrue(self.admin_assignment.activa)

    def test_isolation_other_company(self):
        resp = self.client.get(reverse('auth-assignments-list', kwargs={'empresa_id': self.other.pk}))
        self.assertEqual(resp.status_code, 403)

    def test_limited_admin_cannot_assign_permission_not_owned(self):
        p, _ = Permiso.objects.get_or_create(codigo='usuarios.administrar', defaults={
            'modulo': 'usuarios', 'accion': 'administrar', 'nombre': 'Administrar usuarios'})
        r = Rol.objects.create(empresa=self.company, codigo='power', nombre='Power')
        RolPermiso.objects.create(rol=r, permiso=p)
        MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.employee)
        resp = self.client.post(reverse('auth-assignment-add', kwargs={'empresa_id': self.company.pk}),
                                json.dumps({'usuario_id': self.employee.pk,
                                            'rol_id': str(r.pk)}), content_type='application/json')
        self.assertEqual(resp.status_code, 403)
