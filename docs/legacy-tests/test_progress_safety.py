import io
import tempfile
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from intranet import models as m
from intranet import services as s
from intranet.presentation import _subsection, checklist_sections, curve_points, point_initial


class ProgressSafetyTests(TestCase):
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
        cls.admin = m.User.objects.get(rol="admin_obra")
        cls.reader = m.User.objects.get(rol="lectura")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_point_initial_and_options(self):
        points = [
            dict(id="a", semana=1, fecha=date(2026, 1, 5), programado=0.1, real=0.12),
            dict(id="b", semana=2, fecha=date(2026, 1, 12), programado=0.2, real=None),
        ]
        for p in points:
            p["reprogramado"] = None
        self.assertEqual(point_initial(points)["semana"], 2)
        rows = curve_points(points)
        self.assertEqual(rows[0]["option"], "S1 · 05/01 · registrado")
        self.assertEqual(rows[1]["option"], "S2 · 12/01 · pendiente")
        self.assertEqual(rows[0]["variation"], "+2,0 pp")
        self.assertEqual(rows[0]["inputs"]["real"], "12")
        points[1]["real"] = 0.18
        self.assertEqual(point_initial(points, date(2026, 2, 1))["semana"], 3)

    def test_avance_tabs_keep_curve_in_query(self):
        curves = list(m.Curva.objects.filter(obra=self.obra).order_by("orden"))
        url = f"/obras/{self.obra.pk}/avance"
        response = self.client.get(url)
        self.assertEqual(response.context["active"], curves[0].pk)
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, "Guardar avance", count=len(curves))
        response = self.client.get(url + "?curva=" + curves[1].pk)
        self.assertEqual(response.context["active"], curves[1].pk)
        self.assertEqual(
            self.client.get(url + "?curva=actividades").context["active"], "actividades"
        )
        self.assertEqual(self.client.get(url + "?curva=otra").context["active"], curves[0].pk)
        response = self.client.post(
            url,
            {
                "curva": curves[1].pk,
                "semana": 99,
                "fecha": "2026-10-01",
                "real": 50,
                "programado": 60,
            },
        )
        self.assertRedirects(response, url + "?curva=" + curves[1].pk)

    def test_avance_ids_are_unique(self):
        response = self.client.get(f"/obras/{self.obra.pk}/avance")
        html = response.content.decode()
        self.assertEqual(html.count('id="id_semana"'), 1)
        self.assertEqual(html.count('id="id_real"'), 1)

    def test_pdr_tabs_checklist_and_evaluator(self):
        week = m.Semana.objects.filter(obra=self.obra).latest("numero")
        url = f"/obras/{self.obra.pk}/pdr?semana={week.pk}"
        response = self.client.get(url + "&tab=checklist")
        self.assertEqual(response.context["tab"], "checklist")
        self.assertContains(response, 'type="radio"', count=3 * m.ChecklistItem.objects.count())
        self.assertEqual(self.client.get(url + "&tab=x").context["tab"], "dotacion")
        payload = {"action": "checklist", "evaluado_por": "Prevencionista de turno"}
        for item in m.ChecklistItem.objects.all():
            payload["estado_" + item.pk] = "cumple"
        self.assertEqual(self.client.post(url + "&tab=checklist", payload).status_code, 302)
        self.assertEqual(s.checklist_for(week)["evaluado_por"], "Prevencionista de turno")
        response = self.client.get(url)
        self.assertEqual(response.context["evaluator"], "Prevencionista de turno")

    def test_pdr_read_only_is_disabled(self):
        self.client.force_login(self.reader)
        response = self.client.get(f"/obras/{self.obra.pk}/pdr")
        self.assertContains(response, '<fieldset class="checklist-body" disabled>', html=False)
        self.assertNotContains(response, "Guardar checklist")
        self.assertNotContains(response, "Nueva semana")
        self.assertNotContains(response, "Guardar semana")
        response = self.client.get(f"/obras/{self.obra.pk}/avance")
        self.assertNotContains(response, "Guardar avance")
        self.assertContains(response, "Puntos del programa")

    def test_checklist_sections(self):
        week = m.Semana.objects.filter(obra=self.obra).latest("numero")
        checks = s.checklist_for(week)
        sections = checklist_sections(checks)
        self.assertEqual(sum(sec["total"] for sec in sections), len(checks["rows"]))
        for sec in sections:
            self.assertEqual(sec["cumple"] + sec["no_cumple"] + sec["no_aplica"], sec["total"])
        self.assertEqual(_subsection("1.2 Reglamento interno"), "Reglamento interno")
        self.assertEqual(_subsection("Terreno"), "Terreno")
