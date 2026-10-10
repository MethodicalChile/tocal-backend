import json
from datetime import date

from django.conf import settings
from django.test import SimpleTestCase

from intranet.calculations import (
    business_days,
    compliance,
    curve_state,
    monthly_safety,
    payment_summary,
    rate,
    sales_amounts,
    sales_dashboard,
    staffing,
)


class CalculationTests(SimpleTestCase):
    def test_safety_reference(self):
        self.assertAlmostEqual(rate(1, 3598, 1e6), 277.932, places=2)
        self.assertAlmostEqual(rate(21, 3598, 1e6), 5836.576, places=2)
        self.assertAlmostEqual(rate(1, 28, 100), 3.5714, places=3)
        self.assertEqual(rate(21, 28, 100), 75)
        self.assertEqual(rate(2, 0, 1e6), 0)

    def test_checklist_reference_and_empty(self):
        rows = []
        for cat, yes, no, na in [
            ("antecedentes_generales", 6, 0, 0),
            ("antecedentes_legales", 18, 0, 1),
            ("sso_medio_ambiente", 12, 1, 1),
            ("terreno", 54, 1, 8),
        ]:
            rows += [
                {"categoria": cat, "estado": state}
                for state, n in [("cumple", yes), ("no_cumple", no), ("no_aplica", na)]
                for _ in range(n)
            ]
        c = compliance(rows)
        self.assertEqual([round(x["pct"], 2) for x in c["categories"]], [100, 100, 92.86, 98.41])
        self.assertAlmostEqual(c["total"], 97.817, places=2)
        self.assertEqual(compliance([])["total"], 100)

    def test_staffing_accumulations_and_monthly(self):
        base = dict(
            personal_sc=3,
            hh_sc=168,
            incidentes=0,
            accidentes=0,
            dias_perdidos=0,
            fecha_inicio=date(2026, 4, 6),
        )
        rows = [
            dict(base, personal_operativo=4, personal_adm=3, hh_operativas=176, hh_adm=132),
            dict(
                base,
                personal_operativo=5,
                personal_adm=4,
                hh_operativas=157,
                hh_adm=140,
                incidentes=1,
            ),
        ]
        out = staffing(rows)
        self.assertEqual(out[0]["total_personal"], 7)
        self.assertEqual(out[0]["hh_totales"], 476)
        self.assertEqual(out[1]["hh_acum"], 941)
        self.assertEqual(out[1]["incidentes_acum"], 1)
        month = monthly_safety(rows)[0]
        self.assertEqual(month["hh"], 605)
        self.assertEqual(month["trabajadores"], 9)

    def test_curve_rounding_and_nulls(self):
        state = curve_state(
            [
                dict(semana=42, programado=0.98, real=0.94),
                dict(semana=43, programado=0.99, real=None),
            ]
        )
        self.assertEqual(state["semana"], 42)
        self.assertEqual(state["dias"], -6)
        self.assertAlmostEqual(state["spi"], 0.959, places=3)
        self.assertIsNone(curve_state([]))
        self.assertEqual(business_days(date(2025, 12, 1), date(2026, 6, 30)), 152)

    def test_payments_reference(self):
        amounts = [4152.03, 2833.45, 8258.45, 4114.41, 4161.92, 4160.01, 4403.28, 1635.81, 1778.09]
        r = payment_summary(
            45022.6,
            [dict(monto_uf=x, estado="aprobado") for x in amounts]
            + [dict(monto_uf=999, estado="rechazado")],
            9004.52,
        )
        self.assertAlmostEqual(r["cursado"], 44501.97, places=1)
        self.assertAlmostEqual(r["pendiente"], 520.63, places=1)

    def test_sales_reference(self):
        raw = json.loads((settings.BASE_DIR / "seed-assets/ventas.json").read_text())
        docs = [
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
        data = sales_dashboard(docs, 2026, date(2026, 9, 21))
        annual = {r["year"]: r for r in data["annual"]}
        self.assertAlmostEqual(sum(r["uf"] for r in data["annual"]), 2009035.73, places=1)
        self.assertAlmostEqual(annual[2025]["uf"], 196795.69, places=1)
        self.assertAlmostEqual(annual[2025]["clp"], 7700195658, places=0)
        self.assertAlmostEqual(data["total"]["uf"], 20106.36, places=1)
        self.assertEqual(data["cutoff"], date(2026, 2, 24))
        self.assertAlmostEqual(data["average"], 20106.36 / 2, places=1)
        self.assertEqual(data["clients_count"], 6)
        january = next(r for r in data["monthly"] if r["year"] == 2026 and r["month"] == 1)
        self.assertAlmostEqual(january["uf"], 10151.91, places=1)

    def test_credit_and_exempt_document_amounts(self):
        self.assertEqual(sales_amounts("nota_credito", 1000, 40000)["total"], -1190)
        self.assertEqual(sales_amounts("exenta", -1000, 40000)["total"], 1000)
        with self.assertRaises(ValueError):
            sales_amounts("factura", 1000, 0)
