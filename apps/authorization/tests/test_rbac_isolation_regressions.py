from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.authorization.models import (
    AsignacionRol, Empresa, EmpresaObra, MembresiaEmpresa,
    Permiso, Rol, RolPermiso,
)
from apps.authorization.permissions import effective_permissions, has_permission
from intranet.access import can_edit, can_view, visible_modules
from intranet.models import Obra, ObraUsuario, User


class RBACIsolationRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='rbac-isolation', password='test123', rol='admin_obra')
        self.e1 = Empresa.objects.create(nombre='Empresa Uno')
        self.e2 = Empresa.objects.create(nombre='Empresa Dos')
        self.o1 = Obra.objects.create(nombre='Obra Uno', razon_social='E1', rut='1', servicio='Obra', inicio_contrato=date(2026, 1, 1))
        self.o2 = Obra.objects.create(nombre='Obra Dos', razon_social='E2', rut='2', servicio='Obra', inicio_contrato=date(2026, 1, 1))
        self.link1 = EmpresaObra.objects.create(empresa=self.e1, obra=self.o1)
        self.link2 = EmpresaObra.objects.create(empresa=self.e2, obra=self.o2)
        self.member = MembresiaEmpresa.objects.create(empresa=self.e1, usuario=self.user)
        self.role = Rol.objects.create(empresa=self.e1, codigo='lector', nombre='Lector')
        self.p = Permiso.objects.get(codigo='pdr.ver')
        RolPermiso.objects.create(rol=self.role, permiso=self.p)
        self.assignment = AsignacionRol.objects.create(membresia=self.member, rol=self.role)

    def test_no_cross_company_read(self):
        self.assertTrue(has_permission(user=self.user, permission='pdr.ver', empresa_id=self.e1.pk, obra_id=self.o1.pk))
        self.assertFalse(has_permission(user=self.user, permission='pdr.ver', empresa_id=self.e2.pk, obra_id=self.o2.pk))
        self.assertFalse(can_view(self.user, 'pdr', self.o2))

    def test_corrupt_scope_does_not_grant(self):
        # bulk update salta clean(); el motor de lectura debe ser fail-closed.
        AsignacionRol.objects.filter(pk=self.assignment.pk).update(empresa_obra=self.link2)
        self.assertEqual(effective_permissions(user=self.user, empresa_id=self.e1.pk, obra_id=self.o1.pk), set())
        self.assertFalse(has_permission(user=self.user, permission='pdr.ver', empresa_id=self.e1.pk, obra_id=self.o1.pk))

    def test_anonymous_denied(self):
        self.assertEqual(visible_modules(AnonymousUser()), [])
        self.assertFalse(can_view(AnonymousUser(), 'pdr', self.o1))
        self.assertFalse(can_edit(AnonymousUser(), 'pdr', self.o1))

    def test_legacy_cannot_modify_unassigned_obra(self):
        legacy = User.objects.create_user(username="legacy-rbac", email="legacy-rbac@example.test", password="test123", rol="admin_obra")
        ObraUsuario.objects.create(user=legacy, obra=self.o1)
        self.assertTrue(can_edit(legacy, 'pdr', self.o1))
        self.assertFalse(can_edit(legacy, 'pdr', self.o2))
        self.assertFalse(can_view(legacy, 'pdr', self.o2))
