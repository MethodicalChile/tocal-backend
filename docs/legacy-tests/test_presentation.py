import json
from datetime import date
from types import SimpleNamespace

from django.template import Context, Template
from django.test import SimpleTestCase

from intranet import presentation as p
from intranet.calculations import curve_state, monthly_safety, sales_dashboard, staffing


def point(week, day, programado, real=None, reprogramado=None):
    return dict(
        semana=week,
        fecha=day,
        programado=programado,
        real=real,
        reprogramado=reprogramado,
    )


def curve_entry(points, name="General"):
    return dict(curve=SimpleNamespace(nombre=name), points=points, state=curve_state(points, 151))


def staff_row(week, start, operativo, sc, accidentes=0, dias=0):
    return dict(
        numero=week,
        fecha_inicio=start,
        personal_operativo=operativo,
        personal_adm=2,
        personal_sc=sc,
        hh_operativas=operativo * 45,
        hh_adm=90,
        hh_sc=sc * 45,
        incidentes=0,
        accidentes=accidentes,
        dias_perdidos=dias,
    )


def sale(day, uf, rubro="energia", kind="factura"):
    return dict(
        fecha=day,
        afecto=uf * 38000,
        afecto_uf=uf,
        rubro=rubro,
        rut_cliente="76.000.000-0",
        razon_social="Cliente",
        obra="Obra",
        tipo_documento=kind,
    )


class CurveChartTests(SimpleTestCase):
    def setUp(self):
        self.points = [
            point(2, date(2026, 3, 9), 0.25, 0.2, 0.22),
            point(1, date(2026, 3, 2), 0.1, 0.08),
            point(3, date(2026, 3, 16), 0.5),
        ]

    def test_points_sorted_iso_dates_and_percent_scale(self):
        data = p.curve_chart(curve_entry(self.points), today=date(2026, 3, 10))
        self.assertEqual([x["semana"] for x in data["points"]], [1, 2, 3])
        self.assertEqual(data["points"][0]["fecha"], "2026-03-02")
        self.assertEqual(data["points"][1]["programado"], 25.0)
        self.assertEqual(data["points"][1]["real"], 20.0)
        self.assertIsNone(data["points"][2]["real"])
        self.assertTrue(data["reprogramado"])
        self.assertEqual(data["marker"], {"fecha": "2026-03-10", "label": "Hoy"})
        self.assertIn("real 20,0 %", data["summary"])
        self.assertIn("semana 2", data["summary"])
        json.dumps(data)

    def test_marker_falls_back_to_last_real_point(self):
        data = p.curve_chart(curve_entry(self.points), today=date(2026, 10, 1))
        self.assertEqual(data["marker"], {"fecha": "2026-03-09", "label": "Corte"})

    def test_empty_curve(self):
        data = p.curve_chart(curve_entry([]), today=date(2026, 3, 10))
        self.assertEqual(data["points"], [])
        self.assertIsNone(data["marker"])
        self.assertFalse(data["reprogramado"])
        self.assertIn("sin datos", data["summary"])


class SafetyChartTests(SimpleTestCase):
    def setUp(self):
        self.series = staffing(
            [
                staff_row(1, date(2026, 3, 30), 10, 4),
                staff_row(2, date(2026, 4, 6), 12, 6, accidentes=1, dias=3),
            ]
        )

    def test_staffing_chart_data(self):
        data = p.staffing_chart_data(self.series)
        self.assertEqual(
            data["weeks"][1],
            dict(numero=2, fecha="2026-04-06", tocal=14, subcontrato=6, hh=900.0),
        )
        self.assertIn("Semana 2: 14 personas", data["summary"])
        self.assertEqual(p.staffing_chart_data([])["weeks"], [])

    def test_accidents_chart_data(self):
        data = p.accidents_chart_data(monthly_safety(self.series))
        self.assertEqual([m["label"] for m in data["months"]], ["Mar 26", "Abr 26"])
        self.assertEqual(data["months"][1]["accidentes"], 1)
        self.assertEqual(data["months"][1]["dias_perdidos"], 3)
        self.assertIn("1 accidentes y 3 días perdidos", data["summary"])

    def test_gauge_data_clamps(self):
        self.assertEqual(p.gauge_data(104.2, "PDR")["value"], 100.0)
        self.assertEqual(p.gauge_data(87.46)["value"], 87.5)
        self.assertIsNone(p.gauge_data(None)["value"])


class SalesChartTests(SimpleTestCase):
    def setUp(self):
        docs = [
            sale(date(2024, 1, 5), 100, "industrial"),
            sale(date(2025, 1, 5), 200),
            sale(date(2025, 3, 5), 50, "comercial"),
            sale(date(2026, 1, 5), 300),
            sale(date(2026, 2, 5), 120, "comercial"),
            sale(date(2026, 2, 9), -20, "comercial", "nota_credito"),
        ]
        self.sales = sales_dashboard(docs, 2026, date(2026, 9, 21))

    def test_sectors_annual_in_dashboard(self):
        rows = {(r["year"], r["name"]): r["uf"] for r in self.sales["sectors_annual"]}
        self.assertEqual(rows[(2026, "comercial")], 100)
        self.assertEqual(rows[(2024, "industrial")], 100)

    def test_monthly_compares_three_years(self):
        data = p.sales_monthly_data(self.sales, 2026)
        self.assertEqual([s["year"] for s in data["series"]], [2024, 2025, 2026])
        self.assertEqual(len(data["months"]), 12)
        self.assertEqual(data["series"][2]["uf"][:3], [300.0, 100.0, 0.0])
        self.assertEqual(data["series"][1]["clp"][0], 7600000)
        self.assertEqual(data["current"], 2026)

    def test_annual(self):
        data = p.sales_annual_data(self.sales, 2026)
        self.assertEqual(data["years"], [2024, 2025, 2026])
        self.assertEqual(data["uf"], [100.0, 250.0, 400.0])
        self.assertIn("Mejor año: 2026", data["summary"])

    def test_sector_stack_keeps_fixed_order_and_skips_empty(self):
        data = p.sales_sector_data(self.sales, last=2)
        self.assertEqual(data["years"], [2025, 2026])
        self.assertEqual([s["key"] for s in data["series"]], ["energia", "comercial"])
        self.assertEqual(data["series"][1]["uf"], [50.0, 100.0])
        self.assertEqual(data["series"][1]["name"], "Comercial")

    def test_share_and_spark(self):
        share = p.sales_share_data(self.sales)
        self.assertEqual([i["key"] for i in share["items"]], ["energia", "comercial"])
        self.assertEqual(share["total"], 400.0)
        self.assertIn("Energía con 75,0 %", share["summary"])
        spark = p.sales_spark_data(self.sales, 2026)
        self.assertEqual(spark["values"][:3], [300.0, 100.0, 0.0])
        self.assertEqual(len(spark["labels"]), 12)


class ChartTagTests(SimpleTestCase):
    def render(self, source, **context):
        return Template("{% load tocal %}" + source).render(Context(context))

    def test_chart_tag_emits_container_json_and_summary(self):
        html = self.render(
            '{% chart "curva-s" data id="avance" height=320 zoom=True moneda="uf" %}',
            data={"points": [], "summary": "Curva S <General>"},
        )
        self.assertIn('data-chart="curva-s"', html)
        self.assertIn('data-source="avance-data"', html)
        self.assertIn("--chart-h:320px", html)
        self.assertIn('aria-label="Curva S &lt;General&gt;"', html)
        self.assertIn(" data-zoom", html)
        self.assertIn('data-moneda="uf"', html)
        self.assertIn('<script id="avance-data" type="application/json">', html)
        self.assertIn("\\u003CGeneral\\u003E", html)
        self.assertIn("<noscript>", html)

    def test_chart_tag_without_data(self):
        html = self.render('{% chart "gauge" None id="g" label="Cumplimiento" %}')
        self.assertIn('aria-label="Cumplimiento"', html)
        self.assertIn("{}</script>", html)
        self.assertNotIn("data-zoom", html)
