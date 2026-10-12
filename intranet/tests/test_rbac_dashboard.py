from django.test import TestCase
from django.contrib.auth import get_user_model

from intranet.access import visible_obras, get_obra, can_edit
from intranet.models import Obra, ObraUsuario
from apps.authorization.models import (Empresa, EmpresaObra, MembresiaEmpresa,
    Permiso, Rol, RolPermiso, AsignacionRol)
from django.http import Http404

User = get_user_model()


class DashboardRbacBridgeTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username='bridge-user', email='bridge-user@example.com', password='TestPassword-123!', rol='lectura')
        self.a = Empresa.objects.create(nombre='Empresa A')
        self.b = Empresa.objects.create(nombre='Empresa B')
        self.oa = Obra.objects.create(nombre='Obra A', razon_social='A', rut='A', servicio='Prueba', inicio_contrato='2026-10-12')
        self.ob = Obra.objects.create(nombre='Obra B', razon_social='B', rut='B', servicio='Prueba', inicio_contrato='2026-10-12')
        self.la = EmpresaObra.objects.create(empresa=self.a, obra=self.oa)
        self.lb = EmpresaObra.objects.create(empresa=self.b, obra=self.ob)
        self.permission, _ = Permiso.objects.get_or_create(codigo='obras.ver', defaults={'modulo':'obras','accion':'ver','nombre':'Ver obras'})
        self.member = MembresiaEmpresa.objects.create(usuario=self.u, empresa=self.a)
        self.role = Rol.objects.create(empresa=self.a, codigo='lector', nombre='Lector')
        RolPermiso.objects.create(rol=self.role, permiso=self.permission)

    def test_member_without_assignment_has_no_legacy_fallback(self):
        ObraUsuario.objects.create(user=self.u, obra=self.ob)
        self.assertEqual(list(visible_obras(self.u)), [])

    def test_global_role_only_own_company(self):
        AsignacionRol.objects.create(membresia=self.member, rol=self.role)
        self.assertEqual(list(visible_obras(self.u)), [self.oa])
        with self.assertRaises(Http404):
            get_obra(self.u, self.ob.pk)

    def test_worksite_scoped_role_only_assigned_worksite(self):
        AsignacionRol.objects.create(membresia=self.member, rol=self.role, empresa_obra=self.la)
        self.assertEqual(list(visible_obras(self.u)), [self.oa])

    def test_revoked_membership_cannot_fall_back_to_legacy(self):
        AsignacionRol.objects.create(membresia=self.member, rol=self.role)
        ObraUsuario.objects.create(user=self.u, obra=self.ob)
        self.member.activa = False
        self.member.save(update_fields=['activa'])
        self.assertEqual(list(visible_obras(self.u)), [])

    def test_unmigrated_legacy_user_remains_compatible(self):
        legacy = User.objects.create_user(username='legacy-user', email='legacy-user@example.com', password='TestPassword-123!', rol='lectura')
        ObraUsuario.objects.create(user=legacy, obra=self.ob)
        self.assertEqual(list(visible_obras(legacy)), [self.ob])

    def test_new_rbac_user_cannot_edit_by_legacy_role(self):
        self.u.rol = 'admin_obra'
        self.u.save(update_fields=['rol'])
        AsignacionRol.objects.create(membresia=self.member, rol=self.role)
        self.assertFalse(can_edit(self.u, 'pdr'))
