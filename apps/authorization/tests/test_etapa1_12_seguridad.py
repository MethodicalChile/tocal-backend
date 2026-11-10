"""Pruebas de Etapa 1 (Seguridad, Sesiones y RBAC) y Etapa 12 (Storage, Privacidad y Auditoría)."""
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.authorization.models import (
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
    Permiso,
    RegistroAuditoria,
    Rol,
    RolPermiso,
)
from apps.authorization.services import assign_role
from apps.documents.models import (
    ArchivoDocumentoTrabajador,
    DocumentoTrabajador,
    TipoDocumento,
)
from intranet.models import AsignacionTrabajadorObra, Cargo, Obra, Trabajador, User


class Etapa1Y12SeguridadTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(nombre="Constructora Alfa", rut="76111222-3")
        self.empresa_b = Empresa.objects.create(nombre="Constructora Beta", rut="76333444-5")

        self.obra_1 = Obra.objects.create(
            id="obra-alfa-1",
            nombre="Edificio Norte",
            razon_social="Alfa SpA",
            rut="76111222-3",
            servicio="Edificación",
            inicio_contrato=date(2026, 1, 1),
        )
        self.obra_2 = Obra.objects.create(
            id="obra-alfa-2",
            nombre="Edificio Sur",
            razon_social="Alfa SpA",
            rut="76111222-3",
            servicio="Edificación",
            inicio_contrato=date(2026, 2, 1),
        )
        self.obra_b = Obra.objects.create(
            id="obra-beta-1",
            nombre="Puente Beta",
            razon_social="Beta SpA",
            rut="76333444-5",
            servicio="Obras Civiles",
            inicio_contrato=date(2026, 1, 15),
        )
        EmpresaObra.objects.create(empresa=self.empresa_a, obra=self.obra_1)
        EmpresaObra.objects.create(empresa=self.empresa_a, obra=self.obra_2)
        EmpresaObra.objects.create(empresa=self.empresa_b, obra=self.obra_b)

        self.cargo_a = Cargo.objects.create(
            empresa=self.empresa_a, codigo="maestro", nombre="Maestro"
        )
        self.trabajador_1 = Trabajador.objects.create(
            empresa=self.empresa_a,
            nombres="Pedro",
            apellido_paterno="Soto",
            rut="12345678-9",
        )
        self.trabajador_2 = Trabajador.objects.create(
            empresa=self.empresa_a,
            nombres="Juan",
            apellido_paterno="Pérez",
            rut="98765432-1",
        )
        AsignacionTrabajadorObra.objects.create(
            empresa=self.empresa_a,
            obra=self.obra_1,
            trabajador=self.trabajador_1,
            cargo=self.cargo_a,
            fecha_inicio=date(2026, 1, 10),
        )
        AsignacionTrabajadorObra.objects.create(
            empresa=self.empresa_a,
            obra=self.obra_2,
            trabajador=self.trabajador_2,
            cargo=self.cargo_a,
            fecha_inicio=date(2026, 2, 10),
        )

        # Usuario con rol acotado solo a obra_1
        self.user_obra = User.objects.create_user(
            username="jefe_obra_1",
            email="jefe_obra_1@tocal.local",
            password="testpassword123",
            name="Jefe Obra 1",
        )
        MembresiaEmpresa.objects.create(empresa=self.empresa_a, usuario=self.user_obra)
        self.rol_obra = Rol.objects.create(
            empresa=self.empresa_a, codigo="jefe_obra", nombre="Jefe de Obra"
        )
        for cod in (
            "obras.ver",
            "empleados.ver",
            "documentos.ver",
            "documentos.descargar",
            "documentos.aprobar",
        ):
            RolPermiso.objects.create(
                rol=self.rol_obra, permiso=Permiso.objects.get(codigo=cod)
            )
        assign_role(
            usuario=self.user_obra,
            empresa=self.empresa_a,
            rol=self.rol_obra,
            obra=self.obra_1,
        )

        # Usuario administrador con permiso de auditoría
        self.user_admin = User.objects.create_user(
            username="admin_alfa",
            email="admin_alfa@tocal.local",
            password="testpassword123",
            name="Admin Alfa",
        )
        MembresiaEmpresa.objects.create(empresa=self.empresa_a, usuario=self.user_admin)
        self.rol_admin = Rol.objects.create(
            empresa=self.empresa_a, codigo="admin", nombre="Administrador"
        )
        for perm in Permiso.objects.filter(activo=True):
            RolPermiso.objects.create(rol=self.rol_admin, permiso=perm)
        assign_role(
            usuario=self.user_admin,
            empresa=self.empresa_a,
            rol=self.rol_admin,
        )

    def test_permisos_complementarios_migrados(self):
        esperados = {
            "empresas.ver",
            "empresas.editar",
            "documentos.aprobar",
            "equipos.desactivar",
            "epp.ver",
            "epp.crear",
            "epp.editar",
            "alertas.ver",
            "alertas.configurar",
        }
        existentes = set(
            Permiso.objects.filter(codigo__in=esperados, activo=True).values_list(
                "codigo", flat=True
            )
        )
        self.assertEqual(existentes, esperados)

    def test_acceso_no_autenticado_retorna_401(self):
        r_obras = self.client.get(
            reverse("auth-company-works", args=[self.empresa_a.id])
        )
        self.assertEqual(r_obras.status_code, 401)
        r_docs = self.client.get(reverse("documentos-tipos", args=[self.empresa_a.id]))
        self.assertEqual(r_docs.status_code, 401)

    def test_permisos_por_obra_filtran_obras_trabajadores_y_documentos(self):
        self.client.force_login(self.user_obra)

        # 1. Mis permisos devuelve mapa por obra y unión
        r_perm = self.client.get(
            reverse("auth-my-permissions", args=[self.empresa_a.id])
        )
        self.assertEqual(r_perm.status_code, 200)
        body_perm = r_perm.json()
        self.assertIn("empleados.ver", body_perm["permissions"])
        self.assertEqual(body_perm["global_permissions"], [])
        self.assertIn("obra-alfa-1", body_perm["obra_permissions"])
        self.assertNotIn("obra-alfa-2", body_perm["obra_permissions"])

        # 2. company_works solo lista obra_1
        r_obras = self.client.get(
            reverse("auth-company-works", args=[self.empresa_a.id])
        )
        self.assertEqual(r_obras.status_code, 200)
        ids_obras = [o["id"] for o in r_obras.json()["results"]]
        self.assertEqual(ids_obras, ["obra-alfa-1"])

        # 3. Trabajadores solo lista trabajador_1 (asignado a obra_1), sin RUT (no tiene ver_sensibles)
        r_trab = self.client.get(f"/api/empresas/{self.empresa_a.id}/trabajadores")
        self.assertEqual(r_trab.status_code, 200)
        ids_trab = [t["id"] for t in r_trab.json()["results"]]
        self.assertEqual(ids_trab, [self.trabajador_1.id])
        self.assertNotIn("rut", r_trab.json()["results"][0])

        # 4. Detalle de trabajador_2 (en obra_2) retorna 403
        r_det_2 = self.client.get(
            f"/api/empresas/{self.empresa_a.id}/trabajadores/{self.trabajador_2.id}"
        )
        self.assertEqual(r_det_2.status_code, 403)

        # 5. Documentos de trabajador_1 accesibles con permiso por obra; trabajador_2 denegado
        tipo = TipoDocumento.objects.create(
            empresa=self.empresa_a,
            codigo="charla-odi",
            nombre="Charla ODI",
            categoria="trabajador",
        )
        doc_1 = DocumentoTrabajador.objects.create(
            empresa=self.empresa_a,
            trabajador=self.trabajador_1,
            obra=self.obra_1,
            tipo_documento=tipo,
            creado_por=self.user_admin,
        )
        import hashlib
        pdf_bytes = b"%PDF-1.4\ncontenido"
        archivo = ArchivoDocumentoTrabajador.objects.create(
            documento=doc_1,
            version=1,
            nombre_original="odi.pdf",
            tipo_mime="application/pdf",
            tamano_bytes=len(pdf_bytes),
            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            clave_privada="priv/odi.pdf",
            subido_por=self.user_admin,
        )

        r_docs_1 = self.client.get(
            reverse(
                "documentos-trabajador",
                args=[self.empresa_a.id, self.trabajador_1.id],
            )
        )
        self.assertEqual(r_docs_1.status_code, 200)
        self.assertEqual(len(r_docs_1.json()["results"]), 1)

        r_docs_2 = self.client.get(
            reverse(
                "documentos-trabajador",
                args=[self.empresa_a.id, self.trabajador_2.id],
            )
        )
        self.assertEqual(r_docs_2.status_code, 403)

        # 6. Descarga con documentos.descargar acotado a obra_1 funciona y audita
        with patch(
            "apps.documents.views.private_storage.read_bytes",
            return_value=b"%PDF-1.4\ncontenido",
        ):
            r_dl = self.client.get(
                reverse(
                    "documentos-trabajador-archivo-descargar",
                    args=[
                        self.empresa_a.id,
                        self.trabajador_1.id,
                        doc_1.id,
                        archivo.id,
                    ],
                )
            )
        self.assertEqual(r_dl.status_code, 200)
        self.assertEqual(r_dl["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", r_dl["Cache-Control"])
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                empresa=self.empresa_a,
                accion="documentos.trabajador.archivo.descargar",
                entidad_id=str(archivo.id),
            ).exists()
        )

    def test_auditoria_mutaciones_sin_exponer_rut_y_endpoint_auditoria(self):
        self.client.force_login(self.user_admin)
        r_create = self.client.post(
            f"/api/empresas/{self.empresa_a.id}/trabajadores",
            data='{"nombres":"Lucía","apellido_paterno":"Gómez","rut":"15444333-2"}',
            content_type="application/json",
        )
        self.assertEqual(r_create.status_code, 201)
        audit = RegistroAuditoria.objects.filter(
            empresa=self.empresa_a, accion="trabajador.crear"
        ).first()
        self.assertIsNotNone(audit)
        self.assertNotIn("rut", audit.detalle)
        self.assertNotIn("15444333-2", str(audit.detalle))

        # Endpoint de auditoría accesible para admin
        r_aud = self.client.get(
            reverse("auth-audit-list", args=[self.empresa_a.id])
        )
        self.assertEqual(r_aud.status_code, 200)
        acciones = [x["accion"] for x in r_aud.json()["results"]]
        self.assertIn("trabajador.crear", acciones)

        # Usuario sin auditoria.ver recibe 403
        self.client.force_login(self.user_obra)
        r_aud_denied = self.client.get(
            reverse("auth-audit-list", args=[self.empresa_a.id])
        )
        self.assertEqual(r_aud_denied.status_code, 403)

    def test_comando_verificar_storage_privado_roundtrip(self):
        out = StringIO()
        call_command("verificar_storage_privado", "--roundtrip", stdout=out)
        self.assertIn("exitosa", out.getvalue())
