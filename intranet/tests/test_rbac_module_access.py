from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.authorization.models import (Empresa, EmpresaObra, MembresiaEmpresa,
    Permiso, Rol, RolPermiso, AsignacionRol)
from intranet.access import can_edit, can_view, require_editor, require_viewer
from intranet.models import Obra


class ModulePermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='mod-rbac-user', email='mod-rbac-user@example.com',
            password='Test-Password-123', rol='lectura')
        self.company = Empresa.objects.create(nombre='Empresa Modulos')
        self.other = Empresa.objects.create(nombre='Empresa Ajena')
        self.work = Obra.objects.create(
            nombre='Obra modular', razon_social='Empresa Modulos', rut='PRUEBA',
            servicio='Prueba', inicio_contrato='2026-10-12')
        self.other_work = Obra.objects.create(
            nombre='Obra ajena', razon_social='Empresa Ajena', rut='PRUEBA',
            servicio='Prueba', inicio_contrato='2026-10-12')
        EmpresaObra.objects.create(empresa=self.company, obra=self.work)
        EmpresaObra.objects.create(empresa=self.other, obra=self.other_work)
        member = MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.user)
        self.role = Rol.objects.create(empresa=self.company, codigo='modular', nombre='Modular')
        AsignacionRol.objects.create(membresia=member, rol=self.role)

    def grant(self, code):
        modulo, action = code.split('.')
        perm, _ = Permiso.objects.get_or_create(codigo=code, defaults={
            'modulo': modulo, 'accion': action, 'nombre': code})
        RolPermiso.objects.get_or_create(rol=self.role, permiso=perm)

    def test_view_requires_specific_module_permission(self):
        self.grant('obras.ver')
        self.assertFalse(can_view(self.user, 'pdr', self.work))
        with self.assertRaises(PermissionDenied):
            require_viewer(self.user, 'pdr', self.work)
        self.grant('pdr.ver')
        self.assertTrue(can_view(self.user, 'pdr', self.work))

    def test_edit_requires_its_own_permission(self):
        self.grant('pdr.ver')
        self.assertFalse(can_edit(self.user, 'pdr', self.work))
        self.grant('pdr.editar')
        self.assertTrue(can_edit(self.user, 'pdr', self.work))
        self.assertFalse(can_edit(self.user, 'pdr', self.other_work))

    def test_photos_create_and_delete_are_distinct(self):
        self.grant('fotos.crear')
        self.assertTrue(can_edit(self.user, 'fotos', self.work, action='create'))
        self.assertFalse(can_edit(self.user, 'fotos', self.work, action='delete'))
        with self.assertRaises(PermissionDenied):
            require_editor(self.user, 'fotos', self.work, action='delete')
        self.grant('fotos.eliminar')
        self.assertTrue(can_edit(self.user, 'fotos', self.work, action='delete'))

    def test_reports_have_distinct_edit_and_delete_permissions(self):
        for code in ('informes.ver', 'informes.crear', 'informes.aprobar'):
            self.grant(code)
        self.assertTrue(can_edit(self.user, 'informes', self.work, action='create'))
        self.assertTrue(can_edit(self.user, 'informes', self.work, action='approve'))
        self.assertFalse(can_edit(self.user, 'informes', self.work, action='edit'))
        self.assertFalse(can_edit(self.user, 'informes', self.work, action='delete'))
        self.grant('informes.editar')
        self.assertTrue(can_edit(self.user, 'informes', self.work, action='edit'))
        self.assertFalse(can_edit(self.user, 'informes', self.work, action='delete'))
        self.grant('informes.eliminar')
        self.assertTrue(can_edit(self.user, 'informes', self.work, action='delete'))
        self.assertFalse(can_edit(self.user, 'informes', self.other_work, action='delete'))

    def test_legacy_user_keeps_legacy_edit(self):
        legacy = get_user_model().objects.create_user(
            username='mod-legacy', email='mod-legacy@example.com',
            password='Test-Password-123', rol='admin_obra')
        self.assertTrue(can_edit(legacy, 'pdr'))
