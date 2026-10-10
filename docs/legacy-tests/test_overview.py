import io
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from intranet import models as m
from intranet import services as s
from intranet.presentation import obra_cards, signed_days


def summary_stub(name, variation, activa=True):
    state = None
    if variation is not None:
        state = dict(real=0.5 + variation, programado=0.5, variacion=variation, dias=-3, semana=4)
    return dict(
        obra=SimpleNamespace(pk=name, nombre=name, activa=activa),
        curves=[dict(state=state, points=[])],
        last_staff=None,
        checklist=dict(total=100, rows=[]),
        week=None,
        oldest_pending=0,
        pending=0,
        payments=dict(pct=0, pendiente=0),
        latest_report=None,
    )


class PresentationTests(TestCase):
    def test_signed_days(self):
        self.assertEqual(signed_days(3), "+3 días")
        self.assertEqual(signed_days(-1), "−1 día")
        self.assertEqual(signed_days(0), "0 días")
        self.assertEqual(signed_days(None), "—")

    def test_cards_sorted_by_risk(self):
        cards = obra_cards(
            [
                summary_stub("A al día", 0.01),
                summary_stub("B sin curva", None),
                summary_stub("C atrasada", -0.08),
                summary_stub("D finalizada", -0.2, activa=False),
                summary_stub("E leve", -0.01),
            ],
            {"C atrasada": "energia"},
        )
        self.assertEqual(
            [c["obra"].nombre for c in cards],
            ["C atrasada", "E leve", "A al día", "B sin curva", "D finalizada"],
        )
        self.assertTrue(cards[0]["late"])
        self.assertEqual(cards[0]["rubro_label"], "Energía")


class OverviewViewTests(TestCase):
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
        cls.manager = m.User.objects.get(rol="gerencia")
        cls.admin = m.User.objects.get(rol="admin_obra")
        cls.reader = m.User.objects.get(rol="lectura")

    def test_dashboard_for_manager_shows_sales_without_duplicate_link(self):
        self.client.force_login(self.manager)
        response = self.client.get("/")
        self.assertContains(response, "Hola, " + self.manager.name.split(" ")[0])
        self.assertContains(response, "Ver ventas")
        self.assertContains(response, 'data-chart="spark-barras"')
        self.assertContains(response, 'data-variant="compact"')
        self.assertContains(response, "Abrir obra")
        self.assertNotContains(response, ">Ventas</a>")

    def test_dashboard_hides_sales_for_other_roles(self):
        self.client.force_login(self.admin)
        response = self.client.get("/")
        self.assertNotContains(response, "Ver ventas")
        self.assertNotContains(response, "spark-barras")
        self.assertContains(response, self.obra.nombre)

    def test_dashboard_empty_state(self):
        user = m.User.objects.create_user(
            username="sin-obras",
            email="sin@tocal.cl",
            password="x",
            name="Sin Obras",
            rol="lectura",
        )
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertContains(response, "Todavía no tienes obras asignadas.")
        self.assertContains(response, "0 obras en curso")

    def test_dashboard_adds_no_queries_per_obra(self):
        self.client.force_login(self.manager)

        def overhead():
            with CaptureQueriesContext(connection) as page:
                self.client.get("/")
            summaries = 0
            for obra in m.Obra.objects.all():
                with CaptureQueriesContext(connection) as one:
                    s.obra_summary(obra)
                summaries += len(one)
            return len(page) - summaries

        before = overhead()
        m.Obra.objects.create(
            nombre="OBRA DOS",
            razon_social="Tocal",
            rut="1-9",
            servicio="Prueba",
            inicio_contrato=date(2026, 1, 5),
        )
        self.assertEqual(overhead(), before)

    def test_curve_svg_only_for_the_pdf(self):
        pdf = s.report_context(m.Informe.objects.filter(obra=self.obra).first())
        self.assertIn("<svg", pdf["curves"][0]["svg"])
        self.assertIsNone(s.obra_summary(self.obra, svg=False)["curves"][0]["svg"])

    def test_obra_home_has_curve_tabs_alerts_and_staffing(self):
        self.client.force_login(self.reader)
        response = self.client.get(f"/obras/{self.obra.pk}")
        curves = m.Curva.objects.filter(obra=self.obra).count()
        self.assertContains(response, "data-curve-tab", count=curves if curves > 1 else 0)
        self.assertContains(response, 'data-chart="dotacion"')
        self.assertContains(response, "Requiere atención")
        self.assertContains(response, "Datos del contrato")

    def test_obra_home_requires_assignment(self):
        user = m.User.objects.create_user(
            username="otro", email="otro@tocal.cl", password="x", name="Otro", rol="admin_obra"
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"/obras/{self.obra.pk}").status_code, 404)
