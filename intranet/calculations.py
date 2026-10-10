"""Reglas de las planillas, independientes de las vistas y la base de datos."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import floor

CATEGORIES = ("antecedentes_generales", "antecedentes_legales", "sso_medio_ambiente", "terreno")


def rate(numerator, denominator, factor=1):
    return numerator * factor / denominator if denominator > 0 else 0


def compliance(responses):
    categories = []
    for category in CATEGORIES:
        rows = [r for r in responses if r["categoria"] == category]
        count = len(rows)
        compliant = sum(r["estado"] in ("cumple", "no_aplica") for r in rows)
        categories.append(
            {
                "categoria": category,
                "nombre": category.replace("_", " ").capitalize(),
                "total": count,
                "pct": compliant / count * 100 if count else 100,
            }
        )
    active = [c for c in categories if c["total"]]
    return {
        "categories": categories,
        "total": sum(c["pct"] for c in active) / len(active) if active else 100,
    }


def staffing(rows):
    cumulative = dict(hh_acum=0, incidentes_acum=0, accidentes_acum=0, dias_perdidos_acum=0)
    out = []
    for row in rows:
        r = dict(row)
        r["total_personal"] = r["personal_operativo"] + r["personal_adm"]
        r["hh_tocal"] = r["hh_operativas"] + r["hh_adm"]
        r["hh_totales"] = r["hh_tocal"] + r["hh_sc"]
        for target, source in [
            ("hh_acum", "hh_totales"),
            ("incidentes_acum", "incidentes"),
            ("accidentes_acum", "accidentes"),
            ("dias_perdidos_acum", "dias_perdidos"),
        ]:
            cumulative[target] += r[source]
        out.append({**r, **cumulative})
    return out


def monthly_safety(rows):
    months = {}
    for r in rows:
        key = str(r["fecha_inicio"])[:7]
        m = months.setdefault(
            key, dict(mes=key, accidentes=0, dias_perdidos=0, trabajadores=0, hh=0)
        )
        m["accidentes"] += r["accidentes"]
        m["dias_perdidos"] += r["dias_perdidos"]
        m["trabajadores"] = max(m["trabajadores"], r["personal_operativo"] + r["personal_adm"])
        m["hh"] += r["hh_operativas"] + r["hh_adm"]
    for m in months.values():
        m.update(
            frecuencia=rate(m["accidentes"], m["hh"], 1e6),
            gravedad=rate(m["dias_perdidos"], m["hh"], 1e6),
            accidentabilidad=rate(m["accidentes"], m["trabajadores"], 100),
            siniestralidad=rate(m["dias_perdidos"], m["trabajadores"], 100),
        )
    return [months[k] for k in sorted(months)]


def curve_state(points, days=151):
    real = sorted((p for p in points if p["real"] is not None), key=lambda p: p["semana"])
    if not real or real[-1]["programado"] is None:
        return None
    p = real[-1]
    variation = p["real"] - p["programado"]
    return {
        **p,
        "variacion": variation,
        "spi": p["real"] / p["programado"] if p["programado"] > 0 else 1,
        "dias": floor(variation * days + 0.5),
    }


def business_days(start, end):
    return sum((start + timedelta(days=i)).weekday() < 5 for i in range((end - start).days + 1))


def weighted_progress(activities):
    leaves = [a for a in activities if not a["es_resumen"] and a["peso"]]
    planned = sum(a["peso"] * (a["pct_programa"] or 0) for a in leaves)
    actual = sum(a["peso"] * (a["pct_actual"] or 0) for a in leaves)
    return dict(
        programado=planned,
        actual=actual,
        variacion=actual - planned,
        spi=actual / planned if planned else 1,
    )


def payment_summary(contract, payments, advance=0):
    total = advance + sum(p["monto_uf"] for p in payments if p["estado"] != "rechazado")
    return dict(
        contrato=contract, cursado=total, pendiente=contract - total, pct=rate(total, contract)
    )


def extras_summary(extras, contract):
    approved = [e for e in extras if e["estado"] == "aprobado"]
    review = [e for e in extras if e["estado"] in ("borrador", "presentado")]
    approved_uf = sum((e["monto_aprobado_uf"] or e["monto_uf"] or 0) for e in approved)
    return dict(
        approved=len(approved),
        approved_uf=approved_uf,
        review=len(review),
        review_uf=sum(e["monto_uf"] or 0 for e in review),
        rejected=sum(e["estado"] == "rechazado" for e in extras),
        pct=rate(approved_uf, contract or 0, 100),
    )


def rdi_summary(queries, today, overdue_days=30):
    counts = {"pendiente": 0, "incompleta": 0, "respondida": 0}
    answered_days = []
    oldest = 0
    overdue = 0
    for q in queries:
        counts[q["estado"]] = counts.get(q["estado"], 0) + 1
        if q["estado"] == "pendiente":
            days = (today - q["fecha_envio"]).days
            oldest = max(oldest, days)
            overdue += days > overdue_days
        elif q["fecha_respuesta"]:
            answered_days.append((q["fecha_respuesta"] - q["fecha_envio"]).days)
    return dict(
        total=len(queries),
        counts=counts,
        oldest=oldest,
        overdue=overdue,
        answered=len(answered_days),
        average_days=sum(answered_days) / len(answered_days) if answered_days else None,
    )


def photo_summary(photos, today):
    week_start = today - timedelta(days=6)
    return dict(
        total=len(photos),
        week=sum(week_start <= p["fecha"] <= today for p in photos),
        flagged=sum(p["etiqueta"] in ("problema", "seguridad") for p in photos),
        today=sum(p["fecha"] == today for p in photos),
    )


def batch_start(cutoff, week_start, previous_cutoff=None):
    """El lote comienza al día siguiente del corte del informe anterior."""
    if previous_cutoff:
        return previous_cutoff + timedelta(days=1)
    return min(week_start, cutoff)


def sales_amounts(kind, net, uf):
    uf = Decimal(str(uf))
    if uf <= 0 or not uf.is_finite():
        raise ValueError("La UF debe ser mayor que cero.")
    net = abs(Decimal(str(net))) * (-1 if kind == "nota_credito" else 1)
    if not net.is_finite():
        raise ValueError("El monto debe ser finito.")
    tax = (
        Decimal(0)
        if kind == "exenta"
        else (net * Decimal(".19")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    )
    return dict(
        afecto=float(net),
        iva=float(tax),
        total=float(net + tax),
        afecto_uf=float(net / uf),
        total_uf=float((net + tax) / uf),
    )


def sales_totals(docs):
    return {"uf": sum(d["afecto_uf"] for d in docs), "clp": sum(d["afecto"] for d in docs)}


def sales_dashboard(docs, year, today=None):
    today = today or date.today()
    current = [d for d in docs if d["fecha"].year == year]
    last = max((d["fecha"] for d in current), default=today)
    cutoff = min(last, today) if today.year == year else date(year, 12, 31)
    previous = [
        d
        for d in docs
        if d["fecha"].year == year - 1
        and (d["fecha"].month, d["fecha"].day) <= (cutoff.month, cutoff.day)
    ]
    total, prev = sales_totals(current), sales_totals(previous)
    months = cutoff.month if today.year == year else 12
    annual, monthly, sectors, sectors_annual, clients, works = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    for d in docs:
        annual[d["fecha"].year].append(d)
        monthly[(d["fecha"].year, d["fecha"].month)].append(d)
        sectors_annual[(d["fecha"].year, d["rubro"])].append(d)
    for d in current:
        sectors[d["rubro"]].append(d)
        clients[(d["rut_cliente"], d["razon_social"])].append(d)
        if d.get("obra"):
            works[d["obra"]].append(d)
    invoices = [d for d in current if d["tipo_documento"] != "nota_credito"]
    credits = [d for d in current if d["tipo_documento"] == "nota_credito"]

    def share(value):
        return value / total["uf"] if total["uf"] else 0

    def main_client(rows):
        names = defaultdict(float)
        for d in rows:
            names[d["razon_social"]] += d["afecto_uf"]
        return max(names, key=names.get, default="")

    return dict(
        total=total,
        previous=prev,
        cutoff=cutoff,
        months=months,
        variation=(total["uf"] - prev["uf"]) / prev["uf"] if prev["uf"] else None,
        projection=total["uf"] / months * 12,
        average=total["uf"] / months,
        ticket=sales_totals(invoices)["uf"] / len(invoices) if invoices else 0,
        credits=sales_totals(credits),
        credits_count=len(credits),
        invoices_count=len(invoices),
        clients_count=len({d["rut_cliente"] for d in current}),
        works_count=len(works),
        documents=len(current),
        annual=[dict(year=y, **sales_totals(v)) for y, v in sorted(annual.items())],
        monthly=[dict(year=y, month=m, **sales_totals(v)) for (y, m), v in sorted(monthly.items())],
        sectors=[
            dict(name=k, documents=len(v), share=share(sales_totals(v)["uf"]), **sales_totals(v))
            for k, v in sectors.items()
        ],
        sectors_annual=[
            dict(year=y, name=k, **sales_totals(v)) for (y, k), v in sorted(sectors_annual.items())
        ],
        clients=sorted(
            [
                dict(
                    name=k[1],
                    rut=k[0],
                    documents=len(v),
                    share=share(sales_totals(v)["uf"]),
                    **sales_totals(v),
                )
                for k, v in clients.items()
            ],
            key=lambda x: -x["uf"],
        ),
        works=sorted(
            [
                dict(name=k, client=main_client(v), documents=len(v), **sales_totals(v))
                for k, v in works.items()
            ],
            key=lambda x: -x["uf"],
        ),
    )
