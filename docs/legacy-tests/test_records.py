import io
import re
import tempfile
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from intranet import models as m
from intranet import services as s
from intranet.calculations import batch_start, extras_summary, photo_summary, rdi_summary
from intranet.presentation import rdi_tiles, report_facts


class RecordCalculationTests(SimpleTestCase):
    def test_extras_summary_uses_approved_amount_or_presented(self):
        extras = [
            dict(estado="aprobado", monto_uf=100, monto_aprobado_uf=80),
            dict(estado="aprobado", monto_uf=50, monto_aprobado_uf=None),
            dict(estado="presentado", monto_uf=30, monto_aprobado_uf=None),
            dict(estado="borrador", monto_uf=None, monto_aprobado_uf=None),
            dict(estado="rechazado", monto_uf=999, monto_aprobado_uf=None),
        ]
        result = extras_summary(extras, 1000)
        self.assertEqual(result["approved"], 2)
        self.assertEqual(result["approved_uf"], 130)
        self.assertEqual(result["review"], 2)
        self.assertEqual(result["review_uf"], 30)
        self.assertEqual(result["rejected"], 1)
        self.assertAlmostEqual(result["pct"], 13)
        self.assertEqual(extras_summary([], 0)["pct"], 0)

    def test_rdi_summary_counts_oldest_overdue_and_average(self):
        today = date(2026, 3, 31)
        queries = [
            dict(estado="pendiente", fecha_envio=date(2026, 1, 1), fecha_respuesta=None),
            dict(estado="pendiente", fecha_envio=date(2026, 3, 20), fecha_respuesta=None),
            dict(
                estado="respondida", fecha_envio=date(2026, 1, 1), fecha_respuesta=date(2026, 1, 11)
            ),
            dict(
                estado="incompleta", fecha_envio=date(2026, 2, 1), fecha_respuesta=date(2026, 2, 3)
            ),
            dict(estado="respondida", fecha_envio=date(2026, 2, 1), fecha_respuesta=None),
        ]
        result = rdi_summary(queries, today)
        self.assertEqual(result["counts"], dict(pendiente=2, incompleta=1, respondida=2))
        self.assertEqual(result["oldest"], 89)
        self.assertEqual(result["overdue"], 1)
        self.assertEqual(result["answered"], 2)
        self.assertEqual(result["average_days"], 6)
        empty = rdi_summary([], today)
        self.assertIsNone(empty["average_days"])
        self.assertEqual(rdi_tiles(empty)[3]["value"], "—")
        self.assertEqual(rdi_tiles(result)[0]["tone"], "bad")

    def test_photo_summary_windows(self):
        today = date(2026, 9, 11)
        photos = [
            dict(fecha=today, etiqueta="avance"),
            dict(fecha=date(2026, 9, 5), etiqueta="problema"),
            dict(fecha=date(2026, 9, 4), etiqueta="seguridad"),
            dict(fecha=date(2026, 8, 1), etiqueta="calidad"),
        ]
        self.assertEqual(photo_summary(photos, today), dict(total=4, week=2, flagged=2, today=1))

    def test_batch_start(self):
        self.assertEqual(
            batch_start(date(2026, 9, 11), date(2026, 9, 5), date(2026, 9, 4)), date(2026, 9, 5)
        )
        self.assertEqual(batch_start(date(2026, 9, 3), date(2026, 9, 5)), date(2026, 9, 3))


class RecordPageTests(TestCase):
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
        cls.admin = m.User.objects.get(rol="admin_obra")
        cls.pdr = m.User.objects.get(rol="experto_pdr")
        cls.reader = m.User.objects.get(rol="lectura")

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, path=""):
        return f"/obras/{self.obra.pk}/{path}"

    def test_edp_fixed_rows_totals_and_tiles(self):
        response = self.client.get(self.url("edp"))
        self.assertContains(response, "Monto contractual")
        self.assertContains(response, "Anticipo")
        self.assertContains(response, "Total cursado, incluido anticipo")
        labels = [t["label"] for t in response.context["tiles"]]
        self.assertEqual(
            labels,
            ["Cursado del contrato", "Por cursar", "Estados de pago", "Adicionales aprobados"],
        )
        self.assertTrue(response.context["tiles"][0]["focal"])

    def test_adicionales_tiles(self):
        response = self.client.get(self.url("adicionales"))
        labels = [t["label"] for t in response.context["tiles"]]
        self.assertEqual(labels, ["Aprobados", "En revisión", "Sobre el contrato"])
        self.assertContains(response, "Registrar adicional")

    def test_rdi_filters_overdue_and_counts(self):
        response = self.client.get(self.url("rdi"))
        filters = response.context["filters"]
        self.assertEqual(
            [f[1] for f in filters], ["Todas", "Pendiente", "Incompleta", "Respondida"]
        )
        self.assertEqual(filters[0][2], m.Rdi.objects.filter(obra=self.obra).count())
        response = self.client.get(self.url("rdi?estado=pendiente"))
        rows = response.context["rows"]
        self.assertTrue(rows)
        self.assertTrue(all(r.estado == "pendiente" for r in rows))
        if any(r.overdue for r in rows):
            self.assertContains(response, "is-overdue-days")
        response = self.client.get(self.url("rdi?estado=otra"))
        self.assertEqual(response.context["status"], "")

    def test_rows_clickable_only_for_editors(self):
        self.assertContains(self.client.get(self.url("rdi")), "data-href=")
        self.client.force_login(self.pdr)
        response = self.client.get(self.url("rdi"))
        self.assertNotContains(response, "Registrar consulta")
        self.assertNotContains(response, "data-href=")
        self.assertContains(response, "Ver detalle")

    def test_record_form_required_marker_and_delete(self):
        record = m.Rdi.objects.filter(obra=self.obra).first()
        response = self.client.get(self.url(f"rdi/{record.pk}"))
        self.assertContains(response, "is-required")
        self.assertContains(response, 'form="delete-form"')
        self.assertContains(response, 'id="delete-form"')
        self.assertContains(response, "data-confirm=")
        self.assertContains(response, "errorlist", count=0)
        response = self.client.post(
            self.url(f"rdi/{record.pk}"), {"numero": "", "estado": "pendiente"}
        )
        self.assertContains(response, "errorlist")

    def test_photos_upload_panel_and_filters(self):
        response = self.client.get(self.url("fotos"))
        html = response.content.decode()
        self.assertEqual(html.count("<summary"), 1)
        self.assertIn('id="photos"', html)
        self.assertIn('capture="environment"', html)
        # Solo #photos se envía; la cámara agrega sus archivos a ese campo.
        camera = re.search(r'<input id="photos-camera"[^>]*>', html).group(0)
        self.assertNotIn("name=", camera)
        self.assertIn("Subir fotos", html)
        self.assertEqual(response.context["tiles"][0]["label"], "Fotos en la galería")
        response = self.client.get(self.url("fotos?etiqueta=problema"))
        self.assertTrue(all(p.etiqueta == "problema" for p in response.context["photos"]))
        self.client.force_login(self.reader)
        response = self.client.get(self.url("fotos"))
        self.assertNotContains(response, "<summary")
        self.assertNotContains(response, "Subir fotos")

    def test_reports_list_photo_counts_match_batch(self):
        response = self.client.get(self.url("informes"))
        self.assertContains(response, "Nuevo informe")
        self.assertContains(response, "sin emitir")
        counts = s.report_photo_counts(self.obra, [self.report])
        self.assertEqual(counts[self.report.pk], len(s.report_photos(self.report)["included"]))

    def test_report_editor_fields_actions_and_facts(self):
        response = self.client.get(self.url(f"informes/{self.report.pk}"))
        html = response.content.decode()
        self.assertIn('id="report-form"', html)
        self.assertIn('form="report-form"', html)
        self.assertIn('id="id_comentarios"', html)
        self.assertIn('id="id_posibles_problemas"', html)
        self.assertIn("data-emit", html)
        self.assertIn("Guardar borrador", html)
        self.assertEqual(html.count("Subir fotos</a>"), 1)
        self.assertIn("data-bullet-editor", html)
        labels = [f["label"] for f in response.context["facts"]]
        self.assertEqual(
            labels,
            [
                "Cumplimiento PDR",
                "Avance real / programado",
                "Variación",
                "Dotación",
                "RDI pendientes",
                "Fotos",
            ],
        )
        self.report.estado = "emitido"
        self.report.save(update_fields=["estado"])
        response = self.client.get(self.url(f"informes/{self.report.pk}"))
        self.assertContains(response, "Volver a borrador")
        self.assertNotContains(response, "Guardar borrador")
        self.assertNotContains(response, "data-emit")
        self.client.force_login(self.reader)
        response = self.client.get(self.url(f"informes/{self.report.pk}"))
        self.assertNotContains(response, "Volver a borrador")
        self.assertNotContains(response, ">Eliminar")

    def test_report_facts_without_data(self):
        summary = dict(checklist=dict(total=None), curves=[], pending=0, total_people=0)
        facts = report_facts(summary, dict(included=[]))
        self.assertEqual(facts[0]["value"], "—")
        self.assertEqual(facts[2]["tone"], "gris")
        self.assertEqual(facts[5]["value"], "0 incluidas")
