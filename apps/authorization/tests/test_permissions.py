from datetime import date
from django.test import TestCase
from intranet.models import Obra, User
from apps.authorization.models import (
    Empresa, EmpresaObra, MembresiaEmpresa, Permiso, Rol, RolPermiso,
)
from apps.authorization.permissions import has_permission, effective_permissions
from apps.authorization.services import assign_role, revoke_role
from django.core.exceptions import ValidationError


class PermissionEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u1", password="x", name="U", rol="gerencia")
        self.empresa = Empresa.objects.create(nombre="E1")
        self.otra = Empresa.objects.create(nombre="E2")
        MembresiaEmpresa.objects.create(empresa=self.empresa, usuario=self.user)
        self.rol = Rol.objects.create(empresa=self.empresa, codigo="lector", nombre="Lector")
        self.permiso = Permiso.objects.get(codigo="empleados.ver")
        RolPermiso.objects.create(rol=self.rol, permiso=self.permiso)
        self.obra = Obra.objects.create(nombre="O1", razon_social="E1", rut="R", servicio="Construcción", inicio_contrato=date(2026,1,1))
        self.obra2 = Obra.objects.create(nombre="O2", razon_social="E2", rut="R", servicio="Construcción", inicio_contrato=date(2026,1,1))
        EmpresaObra.objects.create(empresa=self.empresa, obra=self.obra)
        EmpresaObra.objects.create(empresa=self.otra, obra=self.obra2)

    def allowed(self, obra=None, empresa=None):
        return has_permission(user=self.user, permission="empleados.ver", empresa_id=empresa or self.empresa.pk, obra_id=obra)

    def test_no_assignment_denied_even_legacy_gerencia(self):
        self.assertFalse(self.allowed())

    def test_company_role_applies_to_company_and_its_obra(self):
        assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol)
        self.assertTrue(self.allowed())
        self.assertTrue(self.allowed(self.obra.pk))
        self.assertFalse(self.allowed(self.obra2.pk))
        self.assertFalse(self.allowed(empresa=self.otra.pk))
        self.assertEqual(effective_permissions(user=self.user, empresa_id=self.empresa.pk), {"empleados.ver"})

    def test_obra_role_is_not_global(self):
        assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol, obra=self.obra)
        self.assertFalse(self.allowed())
        self.assertTrue(self.allowed(self.obra.pk))

    def test_revoked_role_is_denied(self):
        assignment = assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol)
        revoke_role(asignacion=assignment)
        self.assertFalse(self.allowed())

    def test_inactive_membership_denied(self):
        assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol)
        MembresiaEmpresa.objects.filter(empresa=self.empresa, usuario=self.user).update(activa=False)
        self.assertFalse(self.allowed())

    def test_inactive_user_denied(self):
        assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol)
        self.user.is_active = False
        self.assertFalse(self.allowed())

    def test_no_cross_tenant_grant(self):
        with self.assertRaises(ValidationError):
            assign_role(usuario=self.user, empresa=self.otra, rol=self.rol)
