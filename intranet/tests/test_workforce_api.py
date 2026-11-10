
import json
from datetime import date

from django.test import TestCase

from apps.authorization.models import (
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
    Rol,
    Permiso,
    RolPermiso,
    AsignacionRol,
)
from apps.authorization.permissions import has_permission

from intranet.models import (
    User,
    Obra,
    Cargo,
    Trabajador,
    AsignacionTrabajadorObra,
)


class WorkforceApiTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="tocal_test",
            email="tocal_test@example.test",
            password="test-secret",
            name="Prueba",
        )

        # Empresas
        self.a = Empresa.objects.create(nombre="Empresa A")
        self.b = Empresa.objects.create(nombre="Empresa B")

        # Obras
        self.obra_a = Obra.objects.create(
            nombre="Obra A",
            razon_social="A",
            rut="a",
            servicio="obra",
            inicio_contrato=date(2026, 1, 1),
        )

        self.obra_b = Obra.objects.create(
            nombre="Obra B",
            razon_social="B",
            rut="b",
            servicio="obra",
            inicio_contrato=date(2026, 1, 1),
        )

        # Vínculos entre empresa y obra
        self.enlace_a = EmpresaObra.objects.create(
            empresa=self.a,
            obra=self.obra_a,
        )

        self.enlace_b = EmpresaObra.objects.create(
            empresa=self.b,
            obra=self.obra_b,
        )

        # Membresía en Empresa A
        self.membresia_a = MembresiaEmpresa.objects.create(
            empresa=self.a,
            usuario=self.user,
        )

        # Rol RRHH
        self.rol_a = Rol.objects.create(
            empresa=self.a,
            codigo="rrhh",
            nombre="RRHH",
        )

        for action in ("ver", "crear", "editar", "desactivar"):
            permiso = Permiso.objects.get(
                codigo=f"empleados.{action}"
            )
            RolPermiso.objects.create(
                rol=self.rol_a,
                permiso=permiso,
            )

        # Rol de alcance empresarial.
        # Permite operar sobre las obras de Empresa A.
        self.asignacion_empresa = AsignacionRol.objects.create(
            membresia=self.membresia_a,
            rol=self.rol_a,
            empresa_obra=None,
        )

        self.client.force_login(self.user)

        self.worker_a = Trabajador.objects.create(
            empresa=self.a,
            nombres="María",
            apellido_paterno="A",
            rut="11111111-1",
        )

        self.worker_b = Trabajador.objects.create(
            empresa=self.b,
            nombres="Pedro",
            apellido_paterno="B",
            rut="22222222-2",
        )

        self.cargo_a = Cargo.objects.create(
            empresa=self.a,
            codigo="maestro",
            nombre="Maestro",
        )

        self.cargo_b = Cargo.objects.create(
            empresa=self.b,
            codigo="jefe",
            nombre="Jefe",
        )

    def test_listado_no_incluye_otra_empresa_ni_rut_sin_permiso(self):
        response = self.client.get(
            f"/api/empresas/{self.a.pk}/trabajadores"
        )

        self.assertEqual(response.status_code, 200)

        results = response.json()["results"]

        self.assertEqual(
            [x["id"] for x in results],
            [self.worker_a.pk],
        )

        self.assertNotIn("rut", results[0])

    def test_otra_empresa_denegada(self):
        response = self.client.get(
            f"/api/empresas/{self.b.pk}/trabajadores"
        )

        self.assertEqual(response.status_code, 403)

    def test_no_permite_asignar_cargo_otra_empresa(self):
        # El usuario debe tener permisos sobre Obra A.
        self.assertTrue(
            has_permission(
                user=self.user,
                permission="empleados.editar",
                empresa_id=self.a.pk,
                obra_id=self.obra_a.pk,
            )
        )

        response = self.client.post(
            f"/api/empresas/{self.a.pk}/obras/"
            f"{self.obra_a.pk}/trabajadores/asignaciones",
            data=json.dumps({
                "trabajador_id": str(self.worker_a.pk),
                "cargo_id": str(self.cargo_b.pk),
                "fecha_inicio": "2026-10-01",
            }),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            404,
            response.content.decode("utf-8"),
        )

        self.assertFalse(
            AsignacionTrabajadorObra.objects.filter(
                empresa=self.a,
                obra=self.obra_a,
                trabajador=self.worker_a,
            ).exists()
        )

    def test_no_permite_obra_otra_empresa(self):
        response = self.client.get(
            f"/api/empresas/{self.a.pk}/obras/"
            f"{self.obra_b.pk}/trabajadores/asignaciones"
        )

        self.assertEqual(response.status_code, 404)

    def test_desactivacion_sin_eliminar_registro(self):
        response = self.client.delete(
            f"/api/empresas/{self.a.pk}/trabajadores/"
            f"{self.worker_a.pk}"
        )

        self.assertEqual(response.status_code, 200)

        self.worker_a.refresh_from_db()

        self.assertFalse(self.worker_a.activo)

        self.assertTrue(
            Trabajador.objects.filter(
                pk=self.worker_a.pk
            ).exists()
        )

    def test_crear_asignacion_valida(self):
        self.assertTrue(
            has_permission(
                user=self.user,
                permission="empleados.editar",
                empresa_id=self.a.pk,
                obra_id=self.obra_a.pk,
            )
        )

        response = self.client.post(
            f"/api/empresas/{self.a.pk}/obras/"
            f"{self.obra_a.pk}/trabajadores/asignaciones",
            data=json.dumps({
                "trabajador_id": str(self.worker_a.pk),
                "cargo_id": str(self.cargo_a.pk),
                "fecha_inicio": "2026-10-01",
            }),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            201,
            response.content.decode("utf-8"),
        )

        self.assertTrue(
            AsignacionTrabajadorObra.objects.filter(
                empresa=self.a,
                obra=self.obra_a,
                trabajador=self.worker_a,
                cargo=self.cargo_a,
            ).exists()
        )

    def test_no_permite_editar_obra_sin_permiso(self):
        # Revocamos el único rol del usuario.
        self.asignacion_empresa.activa = False
        self.asignacion_empresa.save()

        self.assertFalse(
            has_permission(
                user=self.user,
                permission="empleados.editar",
                empresa_id=self.a.pk,
                obra_id=self.obra_a.pk,
            )
        )

        response = self.client.post(
            f"/api/empresas/{self.a.pk}/obras/"
            f"{self.obra_a.pk}/trabajadores/asignaciones",
            data=json.dumps({
                "trabajador_id": str(self.worker_a.pk),
                "cargo_id": str(self.cargo_a.pk),
                "fecha_inicio": "2026-10-01",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            AsignacionTrabajadorObra.objects.filter(
                empresa=self.a,
                obra=self.obra_a,
                trabajador=self.worker_a,
            ).exists()
        )
