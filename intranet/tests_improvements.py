import json
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.authorization.models import Empresa, MembresiaEmpresa, Rol, Permiso, RolPermiso, AsignacionRol
from intranet.models import Cargo, Trabajador, SolicitudPrivacidad

User = get_user_model()


class PlatformImprovementsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="admin_test",
            email="admin@tocal.cl",
            password="PasswordSegura123!",
            name="Admin Tocal",
            rol="gerencia",
        )
        self.empresa = Empresa.objects.create(
            nombre="Constructora Tocal Limitada Test",
            rut="76.123.456-7",
            activa=True,
        )
        membresia = MembresiaEmpresa.objects.create(usuario=self.user, empresa=self.empresa, activa=True)
        rol = Rol.objects.create(empresa=self.empresa, codigo="admin", nombre="Administrador", activo=True)
        for code in [
            "empleados.ver",
            "empleados.crear",
            "empleados.editar",
            "empleados.ver_sensibles",
            "documentos.ver",
            "documentos.crear",
            "roles.administrar",
            "auditoria.ver",
        ]:
            mod, acc = code.split(".")
            perm, _ = Permiso.objects.get_or_create(
                codigo=code,
                defaults={"nombre": code, "modulo": mod, "accion": acc, "activo": True},
            )
            RolPermiso.objects.get_or_create(rol=rol, permiso=perm)
        AsignacionRol.objects.create(membresia=membresia, rol=rol, activa=True)
        self.cargo = Cargo.objects.create(empresa=self.empresa, codigo="maestro-primera", nombre="Maestro Primera", activo=True)
        self.client.force_login(self.user)

    def test_bulk_workers_import_and_field_lookup_with_qr_and_pts(self):
        # 1. Carga masiva de cuadrilla
        payload = {
            "lineas_texto": "Juan Andrés; Pérez; Soto; 12.345.678-5\nPedro Pablo; González; Rojas; 15.432.198-K",
        }
        res = self.client.post(
            f"/api/empresas/{self.empresa.id}/trabajadores/carga-masiva",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body["creados"], 2)
        self.assertEqual(Trabajador.objects.filter(empresa=self.empresa).count(), 2)

        # 2. Registrar charla diaria de 5 minutos / AST para la cuadrilla
        worker_ids = list(Trabajador.objects.filter(empresa=self.empresa).values_list("id", flat=True))
        res_charla = self.client.post(
            f"/api/documentos/empresas/{self.empresa.id}/charla-cuadrilla/",
            data=json.dumps({
                "tema": "Charla 5 Minutos — Trabajo en Altura",
                "riesgos_criticos": "Caída distinto nivel, uso de arnés",
                "trabajador_ids": worker_ids,
            }),
            content_type="application/json",
        )
        self.assertEqual(res_charla.status_code, 201)
        self.assertEqual(res_charla.json()["registrados"], 2)

        # 3. Consulta en terreno (RF-15) con código QR y resumen PTS (RF-07)
        res_terreno = self.client.get(f"/api/documentos/empresas/{self.empresa.id}/consulta-terreno/")
        self.assertEqual(res_terreno.status_code, 200)
        t_data = res_terreno.json()
        self.assertEqual(t_data["total"], 2)
        self.assertTrue(t_data["results"][0]["qr_codigo"].startswith("TOCAL-"))
        self.assertIn("resumen_pts", t_data)

    def test_privacy_portability_and_admin_arco_resolution(self):
        # Crear solicitud ARCO+
        res_create = self.client.post(
            "/api/privacidad/solicitudes",
            data=json.dumps({"tipo": "portabilidad", "detalle": "Solicito copia estructurada"}),
            content_type="application/json",
        )
        self.assertEqual(res_create.status_code, 201)
        sol_id = res_create.json()["id"]

        # Resolver solicitud ARCO+ como administrador
        res_patch = self.client.patch(
            f"/api/privacidad/solicitudes/{sol_id}",
            data=json.dumps({"estado": "resuelta"}),
            content_type="application/json",
        )
        self.assertEqual(res_patch.status_code, 200)
        self.assertEqual(res_patch.json()["estado"], "resuelta")

        # Descargar paquete de portabilidad (Ley 21.719)
        res_port = self.client.get("/api/privacidad/portabilidad")
        self.assertEqual(res_port.status_code, 200)
        port_data = res_port.json()
        self.assertEqual(port_data["titular"]["email"], "admin@tocal.cl")
        self.assertEqual(len(port_data["historial_solicitudes_arco"]), 1)

    def test_self_service_profile_update(self):
        res = self.client.post(
            "/api/auth/perfil",
            data=json.dumps({"name": "Administrador General Tocal"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Administrador General Tocal")

    def test_session_inactivity_timeout_and_config(self):
        import time

        res = self.client.get("/api/session")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["inactivity_timeout_seconds"], 300)
        self.assertEqual(data["inactivity_warning_seconds"], 10)

        # Simular más de 5 minutos (301 segundos) de inactividad en la sesión
        session = self.client.session
        session["_last_activity_ts"] = int(time.time()) - 305
        session.save()

        res_expired = self.client.get("/api/session")
        self.assertEqual(res_expired.status_code, 401)
