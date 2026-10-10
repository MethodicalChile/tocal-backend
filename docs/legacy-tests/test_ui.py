from django.template import Context, Template
from django.test import TestCase, override_settings

from intranet import models as m


class UiCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = m.User.objects.create_user(
            username="lectura-ui",
            email="ui@tocal.cl",
            password="x",
            name="Ana Pérez",
            rol="lectura",
        )

    def test_requires_login(self):
        with override_settings(DEBUG=True):
            response = self.client.get("/_ui")
        self.assertEqual(response.status_code, 302)

    def test_hidden_without_debug(self):
        self.client.force_login(self.user)
        with override_settings(DEBUG=False):
            self.assertEqual(self.client.get("/_ui").status_code, 404)

    def test_renders_catalog_with_debug(self):
        self.client.force_login(self.user)
        with override_settings(DEBUG=True):
            response = self.client.get("/_ui")
        self.assertContains(response, 'class="stat-tile')
        self.assertContains(response, 'id="i-building-2"')
        self.assertContains(response, "errorlist")
        self.assertContains(response, 'dialog class="modal"')
        for kind in (
            "curva-s",
            "dotacion",
            "accidentes",
            "gauge",
            "ventas-mensual",
            "ventas-anual",
            "rubros-apilado",
            "dona",
            "spark-barras",
        ):
            self.assertContains(response, f'data-chart="{kind}"')


class ComponentTagTests(TestCase):
    def render(self, source, **context):
        return Template("{% load tocal %}" + source).render(Context(context))

    def test_section_card_places_actions_in_header(self):
        html = self.render(
            "{% section_card title=t tone='focal' %}{% card_actions %}<a>Acción</a>"
            "{% endcard_actions %}<p>Cuerpo</p>{% endsection_card %}",
            t="Avance <b>",
        )
        self.assertIn("card--focal", html)
        self.assertIn("Avance &lt;b&gt;", html)
        self.assertLess(html.index("Acción"), html.index("card__body"))
        self.assertGreater(html.index("Cuerpo"), html.index("card__body"))

    def test_status_badge_and_ring(self):
        html = self.render("{% status_badge 'no_cumple' %}{% progress_ring 140 tone='x' %}")
        self.assertIn("dot-bad", html)
        self.assertIn("No cumple", html)
        self.assertIn("--offset:0.00", html)
        self.assertIn("tone-neutral", html)

    def test_stat_tile_and_icon(self):
        html = self.render(
            '{% stat_tile label="Personas" value=12 bar=150 icon="users" tone="ok" %}'
        )
        self.assertIn("--value:100.0%", html)
        self.assertIn('href="#i-users"', html)
        self.assertIn("tone-ok", html)
