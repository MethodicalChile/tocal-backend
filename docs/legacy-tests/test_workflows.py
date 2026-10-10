import hashlib
import io
import re
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from openpyxl import Workbook
from PIL import Image

from intranet import models as m
from intranet import services as s
from intranet.forms import InformeForm, PuntoForm, VentaForm
from intranet.sales_import import import_workbook


class WorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory(prefix="tocal-tests-")
        cls.override = override_settings(MEDIA_ROOT=Path(cls.media.name))
        cls.override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override.disable()
        cls.media.cleanup()

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.obra = m.Obra.objects.get()
        cls.report = m.Informe.objects.get()
        cls.manager = m.User.objects.get(rol="gerencia")
        cls.admin = m.User.objects.get(rol="admin_obra")
        cls.pdr = m.User.objects.get(rol="experto_pdr")
        cls.reader = m.User.objects.get(rol="lectura")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_all_module_pages_and_print(self):
        self.client.force_login(self.manager)
        paths = [
            "/",
            "/ventas",
            "/ventas/documentos",
            "/ventas/documentos/nuevo",
            "/ventas/importar",
            f"/obras/{self.obra.pk}",
            f"/print/informes/{self.report.pk}",
            f"/obras/{self.obra.pk}/informes/{self.report.pk}",
        ]
        paths += [
            f"/obras/{self.obra.pk}/{module}"
            for module in ("pdr", "avance", "edp", "adicionales", "rdi", "fotos", "informes")
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_anonymous_redirect_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get("/").status_code, 302)
        client.force_login(self.admin)
        self.assertEqual(
            client.post(f"/obras/{self.obra.pk}/pdr", {"action": "new_week"}).status_code, 403
        )
        self.assertEqual(client.get("/logout").status_code, 405)

    def test_email_login_and_legacy_password_upgrade(self):
        salt = "abcdef0123456789abcdef0123456789"
        password = "contraseña nueva"
        legacy = (
            salt
            + ":"
            + hashlib.scrypt(
                password.encode(),
                salt=salt.encode(),
                n=16384,
                r=16,
                p=1,
                dklen=64,
                maxmem=128 * 1024 * 1024,
            ).hex()
        )
        self.admin.set_unusable_password()
        self.admin.legacy_password = legacy
        self.admin.save()
        self.client.logout()
        self.assertFalse(self.client.login(username=self.admin.email, password="incorrecta"))
        self.assertTrue(self.client.login(username=self.admin.email.upper(), password=password))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.legacy_password, "")
        self.assertTrue(self.admin.check_password(password))
        self.admin.is_active = False
        self.admin.save()
        self.assertFalse(self.client.login(username=self.admin.email, password=password))

    def test_pdr_role_cannot_write_rdi_or_sales(self):
        self.client.force_login(self.pdr)
        self.assertNotContains(self.client.get(f"/obras/{self.obra.pk}/rdi"), "Registrar consulta")
        self.assertEqual(self.client.post(f"/obras/{self.obra.pk}/rdi/nuevo", {}).status_code, 403)
        self.assertEqual(self.client.post("/ventas/documentos/nuevo", {}).status_code, 403)
        self.assertEqual(self.client.get("/ventas").status_code, 403)
        self.assertEqual(
            self.client.post(f"/obras/{self.obra.pk}/pdr", {"action": "new_week"}).status_code, 302
        )

    def test_reader_cannot_write_any_module(self):
        self.client.force_login(self.reader)
        for module in (
            "pdr",
            "avance",
            "edp/nuevo",
            "adicionales/nuevo",
            "rdi/nuevo",
            "fotos",
            "informes",
            f"informes/{self.report.pk}",
        ):
            with self.subTest(module=module):
                self.assertEqual(
                    self.client.post(
                        f"/obras/{self.obra.pk}/{module}", {"action": "delete"}
                    ).status_code,
                    403,
                )

    def test_unassigned_obra_and_cross_obra_ids(self):
        other = m.Obra.objects.create(
            nombre="Privada",
            razon_social="Privada",
            rut="1",
            servicio="Otro",
            inicio_contrato=date.today(),
        )
        self.assertEqual(self.client.get(f"/obras/{other.pk}").status_code, 404)
        foreign = m.Foto.objects.create(obra=other, storage_path="private.jpg", fecha=date.today())
        self.assertEqual(self.client.get("/api/files/private.jpg").status_code, 404)
        response = self.client.post(
            f"/obras/{self.obra.pk}/informes/{self.report.pk}",
            {"action": "photo", "foto": foreign.pk, "incluir": "on"},
        )
        self.assertEqual(response.status_code, 404)
        week = m.Semana.objects.create(
            obra=other, numero=1, fecha_inicio=date.today(), fecha_fin=date.today()
        )
        self.assertEqual(
            self.client.get(f"/obras/{self.obra.pk}/pdr?semana={week.pk}").status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/obras/{self.obra.pk}/informes", {"semana": week.pk}).status_code,
            404,
        )

    def test_new_week_staffing_and_checklist_inheritance(self):
        response = self.client.post(f"/obras/{self.obra.pk}/pdr", {"action": "new_week"})
        self.assertEqual(response.status_code, 302)
        week = m.Semana.objects.filter(obra=self.obra).latest("numero")
        self.assertEqual(week.numero, 43)
        self.assertTrue(s.checklist_for(week)["inherited"])
        payload = {
            field.name: 0
            for field in m.Dotacion._meta.fields
            if field.name not in ("id", "semana", "updated_at")
        }
        payload.update(
            action="staffing", personal_operativo=12, personal_adm=4, hh_operativas=504, hh_adm=168
        )
        self.assertEqual(self.client.post(response.url, payload).status_code, 302)
        self.assertEqual(m.Dotacion.objects.get(semana=week).hh_operativas, 504)
        payload = {"action": "checklist"}
        for item in m.ChecklistItem.objects.all():
            payload["estado_" + item.pk] = "cumple"
        payload["estado_" + m.ChecklistItem.objects.first().pk] = "no_cumple"
        self.assertEqual(self.client.post(response.url, payload).status_code, 302)
        self.assertEqual(m.ChecklistRespuesta.objects.filter(evaluacion__semana=week).count(), 102)
        self.assertFalse(s.checklist_for(week)["inherited"])

    def test_validation_preserves_data(self):
        week = m.Semana.objects.filter(obra=self.obra).latest("numero")
        old = m.Dotacion.objects.get(semana=week).personal_operativo
        response = self.client.post(
            f"/obras/{self.obra.pk}/pdr?semana={week.pk}",
            {"action": "staffing", "personal_operativo": -3},
        )
        self.assertContains(response, "errorlist")
        self.assertEqual(m.Dotacion.objects.get(semana=week).personal_operativo, old)
        form = PuntoForm({"semana": 1, "fecha": "2026-10-01", "real": 101, "programado": 98})
        self.assertFalse(form.is_valid())
        form = PuntoForm(
            {"semana": 1, "fecha": "2026-10-01", "real": 94, "programado": 98, "reprogramado": ""}
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["real"], 0.94)
        self.assertIsNone(form.cleaned_data["reprogramado"])

    def test_duplicate_edp_is_form_error_and_delete(self):
        existing = m.EstadoPago.objects.filter(obra=self.obra).first()
        data = {"numero": existing.numero, "monto_uf": 100, "estado": "presentado"}
        response = self.client.post(f"/obras/{self.obra.pk}/edp/nuevo", data)
        self.assertContains(response, "errorlist")
        self.assertEqual(
            m.EstadoPago.objects.filter(obra=self.obra, numero=existing.numero).count(), 1
        )
        self.assertEqual(
            self.client.post(
                f"/obras/{self.obra.pk}/edp/{existing.pk}", {"action": "delete"}
            ).status_code,
            302,
        )
        self.assertFalse(m.EstadoPago.objects.filter(pk=existing.pk).exists())

    def test_bullets_roundtrip_highlights_and_subitems(self):
        data = dict(
            titulo="Informe válido",
            fecha_corte="2026-09-11",
            nota_avance="",
            comentarios="! Se hormigona.\n  - Coordinación con ITO.\nOtra viñeta.",
            posibles_problemas="Riesgo informado.",
        )
        form = InformeForm(data, instance=self.report)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.report.refresh_from_db()
        self.assertEqual(
            self.report.comentarios[0],
            dict(texto="Se hormigona.", destacado=True, sub=["Coordinación con ITO."]),
        )
        self.assertIn("  - Coordinación", str(InformeForm(instance=self.report)["comentarios"]))

    def test_photo_batch_overrides_and_foreign_protection(self):
        old = m.Foto.objects.create(
            obra=self.obra, storage_path="old.jpg", fecha=date(2026, 8, 1), etiqueta="avance"
        )
        excluded = (
            m.Foto.objects.filter(obra=self.obra, fecha__lte=self.report.fecha_corte)
            .exclude(pk=old.pk)
            .first()
        )
        m.InformeFoto.objects.create(
            informe=self.report, foto=old, incluir=True, seccion="problema", orden=-1
        )
        m.InformeFoto.objects.create(informe=self.report, foto=excluded, incluir=False)
        result = s.report_photos(self.report)
        self.assertEqual(result["included"][0]["photo"], old)
        self.assertTrue(result["included"][0]["forced"])
        self.assertNotIn(excluded, [r["photo"] for r in result["included"]])

    def test_photo_upload_compression_and_invalid_batch_atomicity(self):
        img = io.BytesIO()
        Image.new("RGB", (2200, 1100), "red").save(img, format="PNG")
        photo = SimpleUploadedFile("obra.png", img.getvalue(), content_type="image/png")
        result = s.upload_photos(
            self.obra, self.admin, [photo], {"fecha": date(2026, 9, 11), "etiqueta": "avance"}
        )
        self.assertEqual(result[0].ancho, 1800)
        self.assertEqual(result[0].alto, 900)
        self.assertEqual(result[0].fecha, date(2026, 9, 11))
        self.assertTrue(s.private_path(result[0].storage_path).exists())
        before = m.Foto.objects.count()
        good = SimpleUploadedFile("obra.png", img.getvalue(), content_type="image/png")
        bad = SimpleUploadedFile("fake.jpg", b"<script>bad</script>", content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            s.upload_photos(self.obra, self.admin, [good, bad], {"etiqueta": "avance"})
        self.assertEqual(m.Foto.objects.count(), before)
        with self.assertRaises(ValidationError):
            s.private_path("../../etc/passwd")

    def test_report_pdf_emission_and_download(self):
        url = f"/obras/{self.obra.pk}/informes/{self.report.pk}"
        response = self.client.post(url, {"action": "emit"}, follow=True)
        self.assertContains(response, "Informe emitido: PDF generado")
        self.report.refresh_from_db()
        self.assertEqual(self.report.estado, "emitido")
        response = self.client.get("/api/files/" + self.report.pdf_path)
        self.assertEqual(response.status_code, 200)
        data = b"".join(response.streaming_content)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 20000)
        self.assertIn("private", response["Cache-Control"])
        response = self.client.post(url, {"action": "save", "titulo": "No guardar"})
        self.report.refresh_from_db()
        self.assertNotEqual(self.report.titulo, "No guardar")
        self.client.logout()
        self.assertEqual(self.client.get("/api/files/" + self.report.pdf_path).status_code, 302)

    def test_pdf_failure_leaves_draft(self):
        with (
            self.assertLogs("intranet.views", level="ERROR"),
            patch("intranet.services.generate_pdf", side_effect=RuntimeError("PDF failed")),
        ):
            self.client.post(f"/obras/{self.obra.pk}/informes/{self.report.pk}", {"action": "emit"})
        self.report.refresh_from_db()
        self.assertEqual(self.report.estado, "borrador")

    def test_sales_create_credit_duplicate_and_lookup(self):
        self.client.force_login(self.manager)
        data = dict(
            tipo_documento="nota_credito",
            numero=987654,
            fecha="2026-10-01",
            rut_cliente="12.345.678-9",
            razon_social="Cliente nuevo",
            rubro="energia",
            obra="Obra nueva",
            afecto=1000000,
            uf_dia=40000,
        )
        self.assertEqual(self.client.post("/ventas/documentos/nuevo", data).status_code, 302)
        doc = m.Venta.objects.get(numero=987654)
        self.assertEqual(doc.afecto, -1000000)
        self.assertEqual(doc.total, -1190000)
        self.assertEqual(doc.afecto_uf, -25)
        self.assertContains(self.client.post("/ventas/documentos/nuevo", data), "Ya existe")
        lookup = self.client.get("/ventas/consulta?rut=12345678-9").json()
        self.assertEqual(lookup["razon_social"], "Cliente nuevo")

    def workbook(self, invalid=False):
        wb = Workbook()
        ws = wb.active
        ws.title = "BD"
        ws.append(
            [
                "RUT",
                "Razón social",
                "Rubro",
                "Obra",
                "Tipo",
                "N°",
                "Fecha",
                "Afecto",
                "IVA",
                "Total",
                "UF",
            ]
        )
        ws.append(
            [
                "12345678-9",
                "Cliente de prueba",
                "ENERGIA",
                "Obra",
                "FACTURA ELECTRONICA",
                887766,
                date(2026, 10, 1),
                1000000,
                190000,
                1190000,
                40000,
            ]
        )
        if invalid:
            ws.append(
                [
                    "12345678-9",
                    "Cliente",
                    "ENERGIA",
                    "Obra",
                    "FACTURA",
                    887767,
                    "no-fecha",
                    1000,
                    190,
                    1190,
                    0,
                ]
            )
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    def test_excel_import_is_atomic_and_repeatable(self):
        before = m.Venta.objects.count()
        with self.assertRaises(ValidationError):
            import_workbook(self.workbook(invalid=True))
        self.assertEqual(m.Venta.objects.count(), before)
        self.assertEqual(import_workbook(self.workbook()), (1, 0))
        self.assertEqual(import_workbook(self.workbook()), (0, 1))
        self.assertEqual(m.Venta.objects.count(), before + 1)

    def test_uf_outage_requires_manual_value(self):
        data = dict(
            tipo_documento="factura",
            numero=987655,
            fecha="2026-10-01",
            rut_cliente="12345678-9",
            razon_social="Cliente",
            rubro="otros",
            afecto=1000,
        )
        with patch("intranet.services.uf_for_date", return_value=None):
            form = VentaForm(data)
            self.assertFalse(form.is_valid())
            self.assertIn("uf_dia", form.errors)

    def test_report_editor_saves_manual_comments(self):
        url = f"/obras/{self.obra.pk}/informes/{self.report.pk}"
        self.assertContains(self.client.get(url), 'name="comentarios"')
        response = self.client.post(
            url,
            {
                "action": "save",
                "titulo": "Informe semanal",
                "fecha_corte": self.report.fecha_corte.isoformat(),
                "nota_avance": "Avance revisado en obra.",
                "comentarios": "! Losa terminada.\n  - Revisada por la ITO.",
                "posibles_problemas": "Pendiente entrega de materiales.",
            },
        )
        self.assertRedirects(response, url)
        self.report.refresh_from_db()
        self.assertEqual(self.report.estado, "borrador")
        self.assertEqual(
            self.report.comentarios,
            [{"texto": "Losa terminada.", "destacado": True, "sub": ["Revisada por la ITO."]}],
        )
        self.assertEqual(
            self.report.posibles_problemas[0]["texto"], "Pendiente entrega de materiales."
        )

    def test_readonly_record_detail_and_edit_permission(self):
        self.client.force_login(self.reader)
        record = m.Rdi.objects.filter(obra=self.obra).first()
        record.observaciones = "Detalle visible para usuarios de lectura."
        record.save()
        url = f"/obras/{self.obra.pk}/rdi/{record.pk}"
        response = self.client.get(url)
        self.assertContains(response, record.observaciones)
        self.assertContains(response, "disabled")
        self.assertNotContains(response, ">Guardar</button>")
        self.assertEqual(self.client.post(url, {"action": "delete"}).status_code, 403)

    def edit_controls(self):
        base = f"/obras/{self.obra.pk}"
        return {
            f"{base}/avance": ["Guardar avance", "data-point-form", f"{base}/actividad/"],
            f"{base}/pdr": ["Nueva semana", "Guardar semana", 'name="action" value="checklist"'],
            f"{base}/edp": ["Registrar estado de pago", f'href="{base}/edp/nuevo"'],
            f"{base}/adicionales": ["Registrar adicional", f'href="{base}/adicionales/nuevo"'],
            f"{base}/rdi": ["Registrar consulta", f'href="{base}/rdi/nuevo"'],
            f"{base}/fotos": ["Subir fotos", "Subir fotografías", f'href="{base}/fotos/'],
            f"{base}/informes": ["Nuevo informe"],
            f"{base}/informes/{self.report.pk}": [
                "Guardar borrador",
                "Emitir informe (PDF)",
                'value="delete"',
            ],
        }

    def test_reader_sees_no_edit_controls(self):
        for user, visible in ((self.admin, True), (self.reader, False)):
            self.client.force_login(user)
            for path, controls in self.edit_controls().items():
                html = self.client.get(path).content.decode()
                for control in controls:
                    with self.subTest(rol=user.rol, path=path, control=control):
                        self.assertEqual(control in html, visible)

    def test_pdr_expert_navigation_only_shows_prevention_and_photos(self):
        def module_nav(user):
            self.client.force_login(user)
            html = self.client.get(f"/obras/{self.obra.pk}/pdr").content.decode()
            nav = html.split('aria-label="Módulos de obra"', 1)[1].split("</nav>", 1)[0]
            return re.findall(r'href="/obras/[^"]+"', nav), nav

        links, nav = module_nav(self.pdr)
        self.assertEqual(
            links, [f'href="/obras/{self.obra.pk}/pdr"', f'href="/obras/{self.obra.pk}/fotos"']
        )
        self.assertIn("Prevención", nav)
        self.assertIn("Fotografías", nav)
        self.assertEqual(len(module_nav(self.admin)[0]), 8)
        self.client.force_login(self.pdr)
        commands = self.client.get("/").context["command_items"]
        self.assertFalse(any(item["url"].endswith("/avance") for item in commands))
        self.assertTrue(any(item["url"].endswith("/fotos") for item in commands))

    def test_sales_forbidden_for_non_managers(self):
        paths = (
            "/ventas",
            "/ventas/documentos",
            "/ventas/documentos/nuevo",
            "/ventas/importar",
            "/ventas/consulta?rut=78027446-8",
        )
        for user in (self.admin, self.pdr, self.reader):
            self.client.force_login(user)
            self.assertNotContains(self.client.get("/"), 'href="/ventas"')
            for path in paths:
                with self.subTest(rol=user.rol, path=path):
                    self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.manager)
        for path in paths[:4]:
            with self.subTest(rol="gerencia", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_curve_point_edit_is_prefilled(self):
        point = m.PuntoCurva.objects.filter(curva__obra=self.obra, real__isnull=False).last()
        response = self.client.get(f"/obras/{self.obra.pk}/avance?punto={point.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.context["point_form"].initial["real"], point.real * 100)
        self.assertEqual(response.context["selected_curve"], point.curva_id)
