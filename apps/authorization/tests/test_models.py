"""Ejecutar con base local/QA, nunca con la DB productiva conectada."""
from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from intranet.models import Obra, ObraUsuario, User
from apps.authorization.models import (
    AsignacionRol,
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
    Permiso,
    Rol,
    RolPermiso,
)


class RolesMultiempresaTest(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nombre="Empresa A", rut="76000000-1")
        self.empresa_b = Empresa.objects.create(nombre="Empresa B", rut="76000000-2")
        self.user = User.objects.create_user(
            username="prueba-autorizacion", email="autoriza@example.invalid",
            password="clave-de-prueba-no-productiva", name="Usuario de prueba", rol="lectura",
        )
        self.membresia = MembresiaEmpresa.objects.create(
            empresa=self.empresa_a, usuario=self.user
        )
        self.rol_a = Rol.objects.create(empresa=self.empresa_a, codigo="jefe", nombre="Jefe")
        self.rol_b = Rol.objects.create(empresa=self.empresa_b, codigo="admin", nombre="Administrador")
        self.obra_a = Obra.objects.create(
            nombre="Obra A", razon_social="Empresa A", rut="76000000-1",
            servicio="Construcción", inicio_contrato=date(2026, 1, 1),
        )
        self.obra_b = Obra.objects.create(
            nombre="Obra B", razon_social="Empresa B", rut="76000000-2",
            servicio="Construcción", inicio_contrato=date(2026, 1, 1),
        )
        self.vinculo_a = EmpresaObra.objects.create(empresa=self.empresa_a, obra=self.obra_a)
        self.vinculo_b = EmpresaObra.objects.create(empresa=self.empresa_b, obra=self.obra_b)

    def test_rol_empresa_aceptado(self):
        asignacion = AsignacionRol.objects.create(
            membresia=self.membresia, rol=self.rol_a
        )
        self.assertIsNone(asignacion.empresa_obra_id)

    def test_rol_obra_aceptado(self):
        asignacion = AsignacionRol.objects.create(
            membresia=self.membresia, rol=self.rol_a, empresa_obra=self.vinculo_a
        )
        self.assertEqual(asignacion.empresa_obra_id, self.vinculo_a.pk)

    def test_rechaza_rol_de_empresa_ajena(self):
        with self.assertRaises(ValidationError):
            AsignacionRol.objects.create(membresia=self.membresia, rol=self.rol_b)

    def test_rechaza_obra_de_empresa_ajena(self):
        with self.assertRaises(ValidationError):
            AsignacionRol.objects.create(
                membresia=self.membresia, rol=self.rol_a, empresa_obra=self.vinculo_b
            )

    def test_no_permite_duplicar_rol_global(self):
        AsignacionRol.objects.create(membresia=self.membresia, rol=self.rol_a)
        with self.assertRaises(ValidationError):
            AsignacionRol.objects.create(membresia=self.membresia, rol=self.rol_a)

    def test_permiso_por_rol_sin_afectar_catalogo(self):
        permiso = Permiso.objects.get(codigo="empleados.ver")
        RolPermiso.objects.create(rol=self.rol_a, permiso=permiso)
        self.assertTrue(RolPermiso.objects.filter(rol=self.rol_a, permiso=permiso).exists())

    def test_modelos_anteriores_siguen_operativos(self):
        asignacion_anterior = ObraUsuario.objects.create(obra=self.obra_a, user=self.user)
        self.assertEqual(self.user.rol, "lectura")
        self.assertEqual(asignacion_anterior.obra_id, self.obra_a.pk)
