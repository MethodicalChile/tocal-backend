import io
import json
import tempfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from openpyxl import Workbook

from intranet import models as m
from intranet import presentation as p
from intranet.calculations import sales_dashboard
from intranet.templatetags.tocal import clp_short, doc_type


def reference_docs():
    raw = json.loads((settings.BASE_DIR / "seed-assets/ventas.json").read_text())
    return [
        dict(
            fecha=date.fromisoformat(d["fecha"]),
            afecto=d["afecto"],
            afecto_uf=d["afecto"] / d["ufDia"],
            rubro=d["rubro"],
            rut_cliente=d["rutCliente"],
            razon_social=d["razonSocial"],
            obra=d["obra"],
            tipo_documento=d["tipoDocumento"],
        )
        for d in raw
    ]


def doc(day, uf, client="A", rut="1-9", obra="Obra", kind="factura", rubro="energia"):
    return dict(
        fecha=day,
        afecto=uf * 40000,
        afecto_uf=uf,
        rubro=rubro,
        rut_cliente=rut,
        razon_social=client,
        obra=obra,
        tipo_documento=kind,
    )


class SalesCalculationTests(SimpleTestCase):
    def test_reference_data_keeps_totals_and_adds_counts(self):
        data = sales_dashboard(reference_docs(), 2026, date(2026, 9, 21))
        self.assertAlmostEqual(data["total"]["uf"], 20106.36, places=1)
        self.assertEqual(data["clients_count"], 6)
        self.assertEqual(data["invoices_count"] + data["credits_count"], data["documents"])
        self.assertEqual(sum(c["documents"] for c in data["clients"]), data["documents"])
        self.assertAlmostEqual(sum(c["share"] for c in data["clients"]), 1, places=6)
        self.assertAlmostEqual(sum(s["share"] for s in data["sectors"]), 1, places=6)
        self.assertEqual(data["works_count"], len(data["works"]))
        top = data["clients"][0]
        self.assertRegex(top["rut"], r"^\d+-[\dK]$")
        self.assertTrue(all(w["client"] for w in data["works"]))
        monthly = p.sales_monthly_data(data, 2026)
        self.assertEqual([s["year"] for s in monthly["series"]], [2024, 2025, 2026])

    def test_documents_per_client_work_and_credits(self):
        docs = [
            doc(date(2026, 1, 5), 100, "A", "1-9", "Obra 1"),
            doc(date(2026, 1, 9), 50, "A", "1-9", "Obra 1"),
            doc(date(2026, 2, 1), 60, "B", "2-7", "Obra 2", rubro="comercial"),
            doc(date(2026, 2, 3), -10, "A", "1-9", "Obra 1", kind="nota_credito"),
        ]
        data = sales_dashboard(docs, 2026, date(2026, 3, 1))
        clients = {c["rut"]: c for c in data["clients"]}
        self.assertEqual(clients["1-9"]["documents"], 3)
        self.assertEqual(clients["1-9"]["uf"], 140)
        self.assertAlmostEqual(clients["1-9"]["share"], 0.7)
        works = {w["name"]: w for w in data["works"]}
        self.assertEqual(works["Obra 1"]["documents"], 3)
        self.assertEqual(works["Obra 2"]["client"], "B")
        self.assertEqual(data["credits_count"], 1)
        self.assertEqual(data["invoices_count"], 3)
        self.assertEqual(data["works_count"], 2)

    def test_overview_texts_in_both_currencies(self):
        docs = [
            doc(date(2025, 1, 10), 100),
            doc(date(2026, 1, 10), 150),
            doc(date(2026, 2, 10), -30, kind="nota_credito"),
        ]
        data = sales_dashboard(docs, 2026, date(2026, 3, 1))
        overview = p.sales_overview(data, 2026)
        self.assertEqual(overview["total"], {"uf": "UF 120", "clp": "$ 4.800.000"})
        self.assertEqual(overview["total_alt"]["clp"], "UF 120,00")
        self.assertEqual(overview["previous"]["uf"], "UF 100")
        self.assertEqual(overview["variation"], "+20,0 %")
        self.assertEqual(overview["variation_tone"], "ok")
        self.assertEqual(overview["projection"]["clp"], "$ 28,8 M")
        self.assertEqual(overview["credits_tone"], "warn")
        self.assertEqual(overview["credits_hint"], "20,0 % de lo facturado")
        self.assertEqual(overview["documents_hint"], "1 factura · 1 nota de crédito")
        self.assertEqual(overview["sectors"][0]["name"], "Energía")
        self.assertEqual(overview["sectors"][0]["pct"], "100,0 %")

    def test_chart_data_has_pesos(self):
        docs = [doc(date(2025, 1, 10), 100), doc(date(2026, 1, 10), 50, rubro="comercial")]
        data = sales_dashboard(docs, 2026, date(2026, 3, 1))
        stack = p.sales_sector_data(data)
        self.assertEqual(stack["series"][0]["clp"], [4000000, 0])
        share = p.sales_share_data(data)
        self.assertEqual(share["total_clp"], 2000000)
        self.assertEqual(share["items"][0]["clp"], 2000000)

    def test_filters(self):
        self.assertEqual(clp_short(12_345_678), "$ 12,3 M")
        self.assertEqual(clp_short(950_000), "$ 950.000")
        self.assertEqual(doc_type("nota_credito"), "Nota de crédito")
        self.assertEqual(doc_type("factura_electronica"), "Factura electrónica")


class SalesPageTests(TestCase):
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
        cls.manager = m.User.objects.get(rol="gerencia")
        cls.admin = m.User.objects.get(rol="admin_obra")

    def setUp(self):
        self.client.force_login(self.manager)

    def test_dashboard_has_toggle_charts_and_single_book_link(self):
        html = self.client.get("/ventas").content.decode()
        self.assertIn("data-currency-toggle", html)
        for kind in ("ventas-mensual", "ventas-anual", "rubros-apilado", "dona"):
            self.assertIn(f'data-chart="{kind}"', html)
        self.assertEqual(html.count("Libro de ventas</a>"), 1)
        self.assertNotIn(">Ventas</a>", html)
        self.assertIn('data-uf="UF ', html)
        self.assertIn("Principales clientes", html)

    def test_other_roles_are_forbidden(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/ventas").status_code, 403)
        self.assertEqual(self.client.get("/ventas/documentos").status_code, 403)

    def test_book_rows_filters_and_total(self):
        credit = m.Venta.objects.create(
            rut_cliente="12345678-9",
            razon_social="Cliente NC",
            rubro="energia",
            tipo_documento="nota_credito",
            numero=555001,
            fecha=date(2026, 2, 1),
            afecto=-1000000,
            uf_dia=40000,
            afecto_uf=-25,
            total_uf=-29.75,
        )
        response = self.client.get("/ventas/documentos?tipo=nota_credito&q=Cliente NC")
        html = response.content.decode()
        self.assertIn(f">N° {credit.numero}</a>", html)
        self.assertIn('class="badge book-doc__type is-credit">Nota de crédito</span>', html)
        self.assertIn('class="is-credit"', html)
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertEqual(response.context["total_uf"], -25)
        self.assertContains(response, "Registrar documento</a>", count=1)
        self.assertContains(response, "Limpiar")
        empty = self.client.get("/ventas/documentos?tipo=exenta&q=no-existe")
        self.assertContains(empty, "No hay documentos con estos filtros.")

    def test_sale_form_has_summary_and_accented_choices(self):
        response = self.client.get("/ventas/documentos/nuevo")
        self.assertContains(response, "data-sale-summary")
        self.assertContains(response, "data-sale-form")
        self.assertContains(response, ">Factura electrónica</option>")
        self.assertContains(response, ">Urbanización</option>")
        for field in ("numero", "fecha", "rut_cliente", "razon_social", "afecto", "uf_dia"):
            self.assertContains(response, f'id="id_{field}"')

    def test_import_shows_row_errors_table(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "BD"
        ws.append(["RUT", "Razón social", "Rubro", "Obra", "Tipo", "N°", "Fecha", "Afecto"])
        ws.append(["12345678-9", "Cliente", "ENERGIA", "Obra", "FACTURA", 1, "no-fecha", 1000])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        buffer.name = "ventas.xlsx"
        before = m.Venta.objects.count()
        response = self.client.post("/ventas/importar", {"archivo": buffer})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(m.Venta.objects.count(), before)
        self.assertEqual(response.context["row_errors"][0]["row"], "2")
        self.assertIn("Fecha", response.context["row_errors"][0]["detail"])
        self.assertContains(response, "Filas con errores")
        self.assertContains(response, 'role="alert"')
