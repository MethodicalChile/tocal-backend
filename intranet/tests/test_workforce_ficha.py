"""Regresiones para la ficha de trabajador y aislamiento empresarial."""
from datetime import date
from django.test import TestCase
from apps.authorization.models import (
    Empresa, EmpresaObra, MembresiaEmpresa, Rol, Permiso,
    RolPermiso, AsignacionRol,
)
from intranet.models import User, Obra, Trabajador, Cargo, AsignacionTrabajadorObra


class WorkforceFichaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ficha_test", email="ficha_test@example.test",
            password="test-password", name="Prueba Ficha",
        )
        self.company_a = Empresa.objects.create(nombre="Empresa A")
        self.company_b = Empresa.objects.create(nombre="Empresa B")
        self.work_a = Obra.objects.create(
            nombre="Obra A", razon_social="A", rut="a", servicio="obra",
            inicio_contrato=date(2026, 1, 1),
        )
        self.work_b = Obra.objects.create(
            nombre="Obra B", razon_social="B", rut="b", servicio="obra",
            inicio_contrato=date(2026, 1, 1),
        )
        EmpresaObra.objects.create(empresa=self.company_a, obra=self.work_a)
        EmpresaObra.objects.create(empresa=self.company_b, obra=self.work_b)
        member = MembresiaEmpresa.objects.create(empresa=self.company_a, usuario=self.user)
        self.role = Rol.objects.create(empresa=self.company_a, codigo="rrhh", nombre="RRHH")
        self.assignment = AsignacionRol.objects.create(
            membresia=member, rol=self.role, empresa_obra=None,
        )
        self.view = Permiso.objects.get(codigo="empleados.ver")
        RolPermiso.objects.create(rol=self.role, permiso=self.view)
        self.worker_a = Trabajador.objects.create(
            empresa=self.company_a, nombres="María", apellido_paterno="Pérez",
            rut="11111111-1",
        )
        self.worker_b = Trabajador.objects.create(
            empresa=self.company_b, nombres="Pedro", apellido_paterno="López",
        )
        self.role_a = Cargo.objects.create(empresa=self.company_a, codigo="maestro", nombre="Maestro")
        self.role_b = Cargo.objects.create(empresa=self.company_b, codigo="jefe", nombre="Jefe")
        self.history = AsignacionTrabajadorObra.objects.create(
            empresa=self.company_a, trabajador=self.worker_a, obra=self.work_a,
            cargo=self.role_a, fecha_inicio=date(2026, 10, 1),
        )
        self.client.force_login(self.user)

    def detail(self, company, worker):
        return f"/api/empresas/{company.pk}/trabajadores/{worker.pk}"

    def test_ficha_incluye_historial_y_nombres(self):
        response = self.client.get(self.detail(self.company_a, self.worker_a))
        self.assertEqual(response.status_code, 200, response.content.decode())
        result = response.json()
        self.assertEqual(result["record"]["id"], self.worker_a.pk)
        self.assertEqual(len(result["asignaciones"]), 1)
        item = result["asignaciones"][0]
        self.assertEqual(item["obra_id"], self.work_a.pk)
        self.assertEqual(item["obra_nombre"], "Obra A")
        self.assertEqual(item["cargo_nombre"], "Maestro")
        self.assertEqual(item["fecha_inicio"], "2026-10-01")

    def test_no_devuelve_rut_sin_permiso_sensible(self):
        result = self.client.get(self.detail(self.company_a, self.worker_a)).json()
        self.assertNotIn("rut", result["record"])
        self.assertTrue(all("rut" not in row for row in result["asignaciones"]))

    def test_rut_con_permiso_sensible(self):
        sensitive = Permiso.objects.get(codigo="empleados.ver_sensibles")
        RolPermiso.objects.create(rol=self.role, permiso=sensitive)
        result = self.client.get(self.detail(self.company_a, self.worker_a)).json()
        self.assertEqual(result["record"]["rut"], "11111111-1")

    def test_no_lee_trabajador_otra_empresa(self):
        response = self.client.get(self.detail(self.company_b, self.worker_b))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(self.detail(self.company_a, self.worker_b))
        self.assertEqual(response.status_code, 404)

    def test_revocar_rol_bloquea_ficha(self):
        self.assignment.activa = False
        self.assignment.save(update_fields=["activa"])
        response = self.client.get(self.detail(self.company_a, self.worker_a))
        self.assertEqual(response.status_code, 403)
