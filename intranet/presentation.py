"""Datos para gráficos: fechas ISO, porcentajes de 0 a 100, UF con dos decimales
y pesos enteros. `summary` describe el gráfico para lectores de pantalla."""

from django.utils import timezone

from .templatetags.tocal import RUBRO_NAMES, clp, clp_short, number, uf

MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
SECTORS = RUBRO_NAMES


def _pct(value):
    return None if value is None else round(float(value) * 100, 2)


def _uf(value):
    return round(float(value or 0), 2)


def _clp(value):
    return round(float(value or 0))


def _pct_text(value):
    return number(value, 1) + " %"


def curve_chart(entry, today=None):
    points = sorted(entry["points"], key=lambda p: p["semana"])
    state = entry["state"]
    name = entry["curve"].nombre
    data = [
        dict(
            semana=p["semana"],
            fecha=p["fecha"].isoformat(),
            programado=_pct(p["programado"]),
            real=_pct(p["real"]),
            reprogramado=_pct(p["reprogramado"]),
        )
        for p in points
    ]
    marker = None
    if points:
        today = today or timezone.localdate()
        if points[0]["fecha"] <= today <= points[-1]["fecha"]:
            marker = dict(fecha=today.isoformat(), label="Hoy")
        elif state:
            marker = dict(fecha=state["fecha"].isoformat(), label="Corte")
    if state:
        summary = (
            f"Curva S {name}: real {_pct_text(state['real'] * 100)} y programado "
            f"{_pct_text(state['programado'] * 100)} en la semana {state['semana']}."
        )
    elif points:
        summary = f"Curva S {name}: programa de {len(points)} semanas, sin avance real registrado."
    else:
        summary = f"Curva S {name}: sin datos aún."
    return dict(
        points=data,
        reprogramado=any(p["reprogramado"] is not None for p in data),
        marker=marker,
        summary=summary,
    )


def staffing_chart_data(series):
    weeks = [
        dict(
            numero=r["numero"],
            fecha=r["fecha_inicio"].isoformat() if r.get("fecha_inicio") else None,
            tocal=r["total_personal"],
            subcontrato=r["personal_sc"],
            hh=round(float(r["hh_totales"]), 1),
        )
        for r in series
    ]
    if weeks:
        last = weeks[-1]
        summary = (
            f"Dotación de {len(weeks)} semanas. Semana {last['numero']}: {last['tocal']} personas "
            f"Tocal, {last['subcontrato']} de subcontrato y {number(last['hh'], 0)} HH."
        )
    else:
        summary = "Dotación semanal: sin datos aún."
    return dict(weeks=weeks, summary=summary)


def accidents_chart_data(monthly):
    months = []
    for m in monthly:
        year, month = m["mes"].split("-")
        months.append(
            dict(
                mes=m["mes"],
                label=f"{MONTHS[int(month) - 1]} {year[2:]}",
                accidentes=m["accidentes"],
                dias_perdidos=m["dias_perdidos"],
            )
        )
    accidents = sum(m["accidentes"] for m in months)
    lost = sum(m["dias_perdidos"] for m in months)
    summary = (
        f"{accidents} accidentes y {lost} días perdidos en {len(months)} meses."
        if months
        else "Accidentabilidad mensual: sin datos aún."
    )
    return dict(months=months, summary=summary)


def gauge_data(value, label=""):
    if value is None:
        return dict(value=None, label=label, summary=f"{label or 'Indicador'}: sin datos aún.")
    value = round(max(0.0, min(100.0, float(value))), 1)
    return dict(value=value, label=label, summary=f"{label or 'Indicador'}: {_pct_text(value)}.")


def sales_monthly_data(sales, year):
    by_month = {(r["year"], r["month"]): r for r in sales["monthly"]}
    series = []
    for y in range(year - 2, year + 1):
        rows = [by_month.get((y, month), {}) for month in range(1, 13)]
        series.append(
            dict(
                year=y,
                uf=[_uf(r.get("uf")) for r in rows],
                clp=[_clp(r.get("clp")) for r in rows],
            )
        )
    total = sum(series[-1]["uf"])
    return dict(
        months=MONTHS,
        series=series,
        current=year,
        summary=f"Ventas mensuales {year - 2} a {year}. {year}: UF {number(total, 0)} acumuladas.",
    )


def sales_annual_data(sales, year):
    annual = sales["annual"]
    best = max(annual, key=lambda r: r["uf"], default=None)
    return dict(
        years=[r["year"] for r in annual],
        uf=[_uf(r["uf"]) for r in annual],
        clp=[_clp(r["clp"]) for r in annual],
        current=year,
        summary=(
            f"Ventas por año de {annual[0]['year']} a {annual[-1]['year']}. Mejor año: "
            f"{best['year']} con UF {number(best['uf'], 0)}."
            if annual
            else "Ventas por año: sin datos aún."
        ),
    )


def sales_sector_data(sales, last=6):
    years = sorted({r["year"] for r in sales["sectors_annual"]})[-last:]
    totals = {(r["year"], r["name"]): r for r in sales["sectors_annual"]}
    series = []
    for key, name in SECTORS.items():
        rows = [totals.get((y, key), {}) for y in years]
        values = [_uf(r.get("uf")) for r in rows]
        if any(values):
            series.append(
                dict(key=key, name=name, uf=values, clp=[_clp(r.get("clp")) for r in rows])
            )
    return dict(
        years=years,
        series=series,
        summary=(
            f"Ventas por rubro de {years[0]} a {years[-1]}, en UF."
            if years
            else "Ventas por rubro: sin datos aún."
        ),
    )


def sales_share_data(sales):
    items = sorted(
        (
            dict(
                key=r["name"],
                name=SECTORS.get(r["name"], r["name"]),
                uf=_uf(r["uf"]),
                clp=_clp(r["clp"]),
            )
            for r in sales["sectors"]
            if r["uf"] > 0
        ),
        key=lambda r: list(SECTORS).index(r["key"]) if r["key"] in SECTORS else len(SECTORS),
    )
    total = sum(r["uf"] for r in items)
    if items:
        top = max(items, key=lambda r: r["uf"])
        summary = (
            f"Participación por rubro sobre UF {number(total, 0)}. Mayor: {top['name']} "
            f"con {_pct_text(top['uf'] / total * 100)}."
        )
    else:
        summary = "Participación por rubro: sin datos aún."
    return dict(
        items=items,
        total=round(total, 2),
        total_clp=sum(r["clp"] for r in items),
        summary=summary,
    )


def sales_spark_data(sales, year):
    by_month = {r["month"]: r["uf"] for r in sales["monthly"] if r["year"] == year}
    values = [_uf(by_month.get(month)) for month in range(1, 13)]
    return dict(
        labels=MONTHS,
        values=values,
        year=year,
        summary=f"Ventas mensuales {year}: UF {number(sum(values), 0)} acumuladas.",
    )


def sales_note(sales, year):
    text = f"Neto facturado al {sales['cutoff']:%d/%m/%Y}."
    if sales["variation"] is not None:
        value = sales["variation"] * 100
        sign = "+" if value >= 0 else "−"
        text += f" {sign}{number(abs(value), 1)} % frente al mismo período de {year - 1}."
    return text


def _money(uf_value, clp_value, places=0, short=True):
    return dict(uf=uf(uf_value or 0, places), clp=(clp_short if short else clp)(clp_value or 0))


def _signed_pct(fraction):
    value = fraction * 100
    sign = "+" if value > 0.05 else "−" if value < -0.05 else ""
    return f"{sign}{number(abs(value), 1)} %"


def sales_overview(sales, year, limit=10):
    total, previous = sales["total"], sales["previous"]
    months = sales["months"] or 1
    cutoff = sales["cutoff"]
    variation = sales["variation"]
    billed = total["uf"] - sales["credits"]["uf"]
    credits = sales["credits"]
    sectors = sorted(sales["sectors"], key=lambda r: -r["uf"])
    return dict(
        total=_money(total["uf"], total["clp"], short=False),
        total_alt=dict(uf=clp(total["clp"]), clp=uf(total["uf"])),
        monthly_description=f"Neto por mes de emisión, {year - 2} a {year}.",
        sectors_description=f"Participación sobre lo facturado en {year}.",
        clients_description=f"Los que más facturaron en {year}.",
        works_description=f"Facturación por obra en {year}, según el libro.",
        cutoff=f"{cutoff:%d/%m/%Y}",
        previous=_money(previous["uf"], previous["clp"]),
        previous_label=f"Mismo periodo {year - 1}",
        previous_hint=f"Del 01/01 al {cutoff:%d/%m}/{year - 1}",
        variation=None if variation is None else _signed_pct(variation),
        variation_tone=None if variation is None else ("ok" if variation >= 0 else "bad"),
        projection=_money(sales["projection"], total["clp"] / months * 12),
        average=_money(sales["average"], total["clp"] / months),
        months=months,
        months_text=f"{months} {'mes' if months == 1 else 'meses'}",
        documents=sales["documents"],
        documents_hint=(
            f"{sales['invoices_count']} {'factura' if sales['invoices_count'] == 1 else 'facturas'}"
            f" · {sales['credits_count']} "
            f"{'nota de crédito' if sales['credits_count'] == 1 else 'notas de crédito'}"
        ),
        credits=_money(credits["uf"], credits["clp"]),
        credits_tone="warn" if credits["uf"] < 0 else "neutral",
        credits_hint=(
            f"{_pct_text(abs(credits['uf']) / billed * 100)} de lo facturado"
            if credits["uf"] and billed
            else "Sin notas de crédito en el año"
        ),
        clients_count=sales["clients_count"],
        top_client=sales["clients"][0]["name"] if sales["clients"] else "",
        works_count=sales["works_count"],
        ticket=uf(sales["ticket"], 0),
        sectors=[
            dict(
                key=r["name"],
                name=SECTORS.get(r["name"], r["name"]),
                amount=_money(r["uf"], r["clp"]),
                pct=_pct_text(r["share"] * 100),
                width=round(max(0, min(1, r["share"])) * 100, 1),
            )
            for r in sectors
            if r["uf"] > 0
        ],
        clients=[
            dict(
                name=r["name"],
                rut=r["rut"],
                documents=r["documents"],
                amount=_money(r["uf"], r["clp"]),
                pct=_pct_text(r["share"] * 100),
                width=round(max(0, min(1, r["share"])) * 100, 1),
            )
            for r in sales["clients"][:limit]
        ],
        works=[
            dict(
                name=r["name"],
                client=r["client"],
                documents=r["documents"],
                amount=_money(r["uf"], r["clp"]),
            )
            for r in sales["works"][:limit]
        ],
        more_clients=max(0, len(sales["clients"]) - limit),
        more_works=max(0, len(sales["works"]) - limit),
    )


def progress_tone(variation):
    """Recibe una fracción; menos de −0,02 indica un atraso mayor a 2 puntos porcentuales."""
    if variation is None:
        return "gris"
    if variation < -0.02:
        return "bad"
    return "warn" if variation < 0 else "ok"


def compliance_tone(total):
    if total is None:
        return "gris"
    if total >= 95:
        return "ok"
    return "warn" if total >= 80 else "bad"


def signed_days(days):
    if days is None:
        return "—"
    sign = "+" if days > 0 else "−" if days < 0 else ""
    return f"{sign}{abs(days)} {'día' if abs(days) == 1 else 'días'}"


def _signed_pp(variation):
    points = variation * 100
    sign = "+" if points > 0.05 else "−" if points < -0.05 else ""
    return f"{sign}{number(abs(points), 1)} pp"


RISK_ORDER = {"bad": 0, "warn": 1, "ok": 2, "gris": 3}


def obra_card(summary, rubro=None):
    obra = summary["obra"]
    main = summary["curves"][0] if summary["curves"] else None
    state = main["state"] if main else None
    variation = state["variacion"] if state else None
    last = summary["last_staff"] or {}
    pdr = summary["checklist"]["total"] if summary["week"] else None
    oldest = summary["oldest_pending"]
    return dict(
        obra=obra,
        rubro=rubro,
        rubro_label=SECTORS.get(rubro, ""),
        state=state,
        progress_tone=progress_tone(variation),
        late=variation is not None and variation < -0.02,
        delay=signed_days(state["dias"]) if state else None,
        pdr=pdr,
        pdr_tone=compliance_tone(pdr),
        payments=summary["payments"],
        pending=summary["pending"],
        pending_hint=f"{oldest} días la más antigua" if summary["pending"] else "Al día",
        accidents=last.get("accidentes_acum", 0),
        lost_days=last.get("dias_perdidos_acum", 0),
        latest_report=summary["latest_report"],
        chart=curve_chart(main) if main and main["points"] else None,
    )


def obra_cards(summaries, rubros=None):
    rubros = rubros or {}
    cards = [obra_card(s, rubros.get(s["obra"].pk)) for s in summaries]
    return sorted(
        cards,
        key=lambda c: (
            not c["obra"].activa,
            RISK_ORDER[c["progress_tone"]],
            c["state"]["variacion"] if c["state"] else 0,
            c["obra"].nombre,
        ),
    )


def obra_overview(summary, late_activities=(), today=None):
    obra = summary["obra"]
    curves = []
    for index, entry in enumerate(summary["curves"]):
        state = entry["state"]
        curves.append(
            dict(
                id=f"curva-{index + 1}",
                name=entry["curve"].nombre,
                description=entry["curve"].descripcion or "",
                state=state,
                tone=progress_tone(state["variacion"] if state else None),
                chart=curve_chart(entry, today),
            )
        )
    state = curves[0]["state"] if curves else None
    pdr = summary["checklist"]["total"] if summary["week"] else None
    last = summary["last_staff"]
    payments = summary["payments"]
    accidents = last["accidentes_acum"] if last else 0

    alerts = obra_alerts(summary, late_activities)

    def day(value):
        return value.strftime("%d/%m/%Y") if value else "—"

    return dict(
        curve_tabs=curves,
        main_state=state,
        delay=signed_days(state["dias"]) if state else "—",
        delay_hint=(
            f"SPI {number(state['spi'], 2)} · {_signed_pp(state['variacion'])} vs. programa"
            if state
            else "Sin avance real registrado"
        ),
        delay_tone=progress_tone(state["variacion"] if state else None),
        pdr=pdr,
        pdr_text=_pct_text(pdr) if pdr is not None else "—",
        pdr_tone=compliance_tone(pdr),
        pdr_hint=(
            f"Checklist DS 76 y DS 44, semana {summary['week'].numero}"
            if summary["week"]
            else "Sin semanas registradas"
        ),
        billing_hint=f"{uf(payments['cursado'], 0)} cursadas de {uf(payments['contrato'], 0)}",
        people_hint=(
            f"{last['total_personal']} Tocal · {last['personal_sc']} subcontrato"
            if last
            else "Sin dotación declarada"
        ),
        pending_tone="warn" if summary["pending"] else "ok",
        pending_hint=(
            f"La más antigua lleva {summary['oldest_pending']} días"
            if summary["pending"]
            else "Todas respondidas"
        ),
        accidents=accidents,
        accidents_tone="bad" if accidents else "ok",
        lost_days=last["dias_perdidos_acum"] if last else 0,
        staffing_chart=staffing_chart_data(summary["series"]),
        alerts=alerts,
        alerts_note=(
            "Sin temas abiertos."
            if not alerts
            else "1 tema abierto."
            if len(alerts) == 1
            else f"{len(alerts)} temas abiertos."
        ),
        contract_facts=[
            ("Monto contractual", uf(payments["contrato"])),
            ("Anticipo", uf(obra.anticipo_uf)),
            ("Cursado, incluido anticipo", uf(payments["cursado"])),
            ("Por cursar", uf(payments["pendiente"])),
            ("Adicionales aprobados", uf(summary["extras_total"])),
            ("Inicio de contrato", day(obra.inicio_contrato)),
            ("Término de contrato", day(obra.termino_contrato)),
            ("Programa aprobado", day(obra.fecha_programa_aprobado)),
        ],
        obra_facts=[
            ("Mandante", obra.mandante),
            ("Razón social", obra.razon_social),
            ("RUT", obra.rut),
            ("Servicio", obra.servicio),
            ("Dirección", obra.direccion),
            ("Administrador de contrato", obra.adm_contrato),
            ("Asesor PDR", obra.asesor_pdr),
            ("Asesor mutualidad", obra.asesor_mutual),
        ],
    )


def obra_alerts(summary, late_activities=()):
    obra = summary["obra"]
    alerts = []
    state = summary["curves"][0]["state"] if summary["curves"] else None
    if state and state["variacion"] < -0.02:
        alerts.append(
            dict(
                tone="bad",
                icon="activity",
                title=f"Avance {_signed_pp(state['variacion'])} bajo el programa",
                text=f"{signed_days(state['dias'])} de desvío en la semana {state['semana']}.",
                href=f"/obras/{obra.pk}/avance",
                action="Revisar avance",
            )
        )
    if late_activities:
        names = ", ".join(late_activities[:2])
        more = len(late_activities) - 2
        alerts.append(
            dict(
                tone="bad",
                icon="clock",
                title=(
                    "1 actividad atrasada"
                    if len(late_activities) == 1
                    else f"{len(late_activities)} actividades atrasadas"
                ),
                text=names + (f" y {more} más." if more > 0 else "."),
                href=f"/obras/{obra.pk}/avance",
                action="Ver programa",
            )
        )
    pdr = summary["checklist"]["total"] if summary["week"] else None
    if pdr is not None and pdr < 80:
        failing = sum(r["estado"] == "no_cumple" for r in summary["checklist"]["rows"])
        alerts.append(
            dict(
                tone="bad",
                icon="shield-check",
                title=f"Cumplimiento en prevención de {_pct_text(pdr)}",
                text=f"Bajo el mínimo de 80 %. {failing} ítems del checklist no cumplen.",
                href=f"/obras/{obra.pk}/pdr",
                action="Abrir checklist",
            )
        )
    old = sorted(
        (r for r in summary["queries"] if r.estado == "pendiente" and r.days_open > 30),
        key=lambda r: -r.days_open,
    )
    if old:
        numbers = ", ".join(f"N° {r.numero}" for r in old[:4])
        alerts.append(
            dict(
                tone="warn",
                icon="message-circle-question",
                title=(
                    "1 consulta sin respuesta hace más de 30 días"
                    if len(old) == 1
                    else f"{len(old)} consultas sin respuesta hace más de 30 días"
                ),
                text=f"{numbers}{' …' if len(old) > 4 else ''}. La más antigua lleva "
                f"{old[0].days_open} días.",
                href=f"/obras/{obra.pk}/rdi",
                action="Ver RDI",
            )
        )
    report = summary["latest_report"]
    if report and report.estado == "borrador":
        alerts.append(
            dict(
                tone="warn",
                icon="file-text",
                title="Informe en borrador",
                text=f"Corte al {report.fecha_corte:%d/%m/%Y}, todavía sin emitir.",
                href=f"/obras/{obra.pk}/informes/{report.pk}",
                action="Abrir informe",
            )
        )
    return alerts


def obra_header(summary):
    state = summary["curves"][0]["state"] if summary["curves"] else None
    pdr = summary["checklist"]["total"] if summary["week"] else None
    return dict(
        real=state["real"] if state else None,
        variation=state["variacion"] if state else None,
        progress_tone=progress_tone(state["variacion"] if state else None),
        pdr=pdr,
        pdr_tone=compliance_tone(pdr),
        pending=summary["pending"],
        people=summary["total_people"],
    )


CURVE_NAMES = {"general": "General", "ruta_critica": "Ruta crítica", "accesos": "Accesos"}


def _input_pct(value):
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}".rstrip("0").rstrip(".")


def point_initial(points, today=None):
    """Propone la primera semana pendiente después del último avance real."""
    ordered = sorted(points, key=lambda p: p["semana"])
    last = max((p["semana"] for p in ordered if p["real"] is not None), default=0)
    for p in ordered:
        if p["semana"] > last and p["real"] is None:
            return dict(
                semana=p["semana"],
                fecha=p["fecha"],
                programado=p["programado"],
                reprogramado=p["reprogramado"],
            )
    return dict(
        semana=max((p["semana"] for p in ordered), default=0) + 1,
        fecha=today or timezone.localdate(),
    )


def curve_points(points):
    rows = []
    for p in sorted(points, key=lambda p: p["semana"]):
        both = p["real"] is not None and p["programado"] is not None
        variation = p["real"] - p["programado"] if both else None
        status = "pendiente" if p["real"] is None else "registrado"
        rows.append(
            dict(
                id=p["id"],
                semana=p["semana"],
                fecha=p["fecha"],
                programado=p["programado"],
                real=p["real"],
                variation=_signed_pp(variation) if variation is not None else "—",
                tone="gris" if variation is None else "bad" if variation < -0.0005 else "ok",
                pending=p["real"] is None,
                option=f"S{p['semana']} · {p['fecha']:%d/%m} · {status}",
                inputs=dict(
                    fecha=p["fecha"].isoformat(),
                    programado=_input_pct(p["programado"]),
                    real=_input_pct(p["real"]),
                    reprogramado=_input_pct(p["reprogramado"]),
                ),
            )
        )
    return rows


def avance_tabs(curves, today=None):
    tabs = []
    for index, entry in enumerate(curves):
        curve = entry["curve"]
        state = entry["state"]
        variation = state["variacion"] if state else None
        points = curve_points(entry["points"])
        tabs.append(
            dict(
                key=curve.pk,
                id=f"curva-{index + 1}",
                name=CURVE_NAMES.get(curve.variante, curve.nombre),
                title=curve.nombre,
                description=curve.descripcion or "Avance programado, real y reprogramado.",
                state=state,
                tone=progress_tone(variation),
                delay=signed_days(state["dias"]) if state else "—",
                variation=_signed_pp(variation) if state else None,
                spi=number(state["spi"], 2) if state else None,
                tile_hint=(
                    f"de {_pct_text(state['programado'] * 100)} programado · "
                    f"{signed_days(state['dias'])}"
                    if state
                    else "Sin avance real registrado"
                ),
                chart=curve_chart(entry, today),
                points=points,
                new_week=max((p["semana"] for p in points), default=0) + 1,
                last_real=max((p["semana"] for p in points if not p["pending"]), default=None),
            )
        )
    return tabs


def activity_rows(activities):
    return [
        dict(
            obj=a,
            group=bool(a.es_resumen) or a.peso is None,
            depth=max(0, min(a.nivel or 0, 5)),
            programado=_pct(a.pct_programa),
            real=_pct(a.pct_actual),
            late=a.status == "atraso",
        )
        for a in activities
    ]


CHECKLIST_NAMES = {
    "antecedentes_generales": "Antecedentes generales",
    "antecedentes_legales": "Antecedentes legales",
    "sso_medio_ambiente": "SSO y medio ambiente",
    "terreno": "Terreno",
}


def _subsection(text):
    text = (text or "").strip()
    head, _, rest = text.partition(" ")
    return rest if rest and head.replace(".", "").isdigit() else text


def checklist_sections(checks):
    sections = {}
    for row in checks["rows"]:
        item = row["item"]
        section = sections.setdefault(
            item.categoria,
            dict(
                key=item.categoria,
                name=CHECKLIST_NAMES.get(item.categoria, item.get_categoria_display()),
                rows=[],
                cumple=0,
                no_cumple=0,
                no_aplica=0,
                last_sub=None,
            ),
        )
        sub = _subsection(item.subseccion)
        section["rows"].append(dict(row, subheader=sub if sub != section["last_sub"] else ""))
        section["last_sub"] = sub
        if row["estado"] in ("cumple", "no_cumple", "no_aplica"):
            section[row["estado"]] += 1
    result = []
    for section in sections.values():
        total = len(section["rows"])
        pct = (section["cumple"] + section["no_aplica"]) / total * 100 if total else 100
        result.append(
            dict(
                section,
                total=total,
                pct=pct,
                pct_text=number(pct, 0) + " %",
                tone=compliance_tone(pct),
            )
        )
    return result


def pdr_overview(checks, week, series):
    current = series[-1] if series and week and series[-1]["numero"] == week.numero else None
    last = series[-1] if series else None
    total = checks["total"] if checks else None
    failing = sum(r["estado"] == "no_cumple" for r in checks["rows"]) if checks else 0
    items = len(checks["rows"]) if checks else 0
    accidents = current["accidentes"] if current else 0
    if not checks:
        compliance_hint = "Sin semanas registradas"
    elif failing:
        compliance_hint = f"{failing} de {items} ítems no cumplen"
    else:
        compliance_hint = f"Los {items} ítems cumplen o no aplican"
    return dict(
        compliance=total,
        compliance_text=_pct_text(total) if total is not None else "—",
        compliance_tone=compliance_tone(total),
        compliance_hint=compliance_hint,
        people=number(current["total_personal"] + current["personal_sc"], 0) if current else "—",
        people_hint=(
            f"{current['total_personal']} Tocal · {current['personal_sc']} subcontrato"
            if current
            else "Dotación de la semana sin declarar"
        ),
        hh_acum=number(last["hh_acum"], 0) if last else "—",
        hh_hint=(
            f"{number(current['hh_totales'], 0)} HH esta semana"
            if current
            else "Desde el inicio de la obra"
        ),
        incidents=current["incidentes"] if current else "—",
        incidents_tone="warn" if current and current["incidentes"] else "neutral",
        incidents_hint=f"{last['incidentes_acum']} acumulados en la obra" if last else "",
        accidents=accidents if current else "—",
        accidents_tone="bad" if accidents else "neutral",
        accidents_hint=(
            f"{current['dias_perdidos']} días perdidos · {last['accidentes_acum']} acumulados"
            if current
            else ""
        ),
    )


def safety_rows(monthly):
    rows = []
    for m in monthly:
        year, month = m["mes"].split("-")
        rows.append(dict(m, label=f"{MONTHS[int(month) - 1]} {year}"))
    return rows


def _tile(label, value, hint="", tone="neutral", icon="", **extra):
    return dict(label=label, value=value, hint=hint, tone=tone, icon=icon, **extra)


def _plural(count, one, many):
    return f"{number(count, 0)} {one if count == 1 else many}"


def payments_tiles(payments, edp, extras):
    paid = sum(p.estado == "pagado" for p in edp)
    in_process = sum(p.estado in ("presentado", "aprobado", "facturado") for p in edp)
    pct = payments["pct"] * 100
    return [
        _tile(
            "Cursado del contrato",
            _pct_text(pct),
            f"{uf(payments['cursado'])} de {uf(payments['contrato'])}, incluido anticipo",
            tone="accent",
            ring=pct,
            focal=True,
            size="lg",
            css="span-2",
        ),
        _tile(
            "Por cursar",
            uf(payments["pendiente"]),
            f"{_pct_text(max(0, 100 - pct))} del contrato",
            icon="clock",
        ),
        _tile(
            "Estados de pago",
            number(len(edp), 0),
            f"{paid} pagados · {in_process} en trámite",
            icon="receipt",
        ),
        _tile(
            "Adicionales aprobados",
            uf(extras["approved_uf"]),
            _plural(extras["approved"], "adicional aprobado", "adicionales aprobados"),
            icon="file-plus",
        ),
    ]


def extras_tiles(extras):
    return [
        _tile(
            "Aprobados",
            uf(extras["approved_uf"]),
            _plural(extras["approved"], "adicional aprobado", "adicionales aprobados"),
            tone="accent",
            focal=True,
            size="lg",
            icon="circle-check",
            css="span-2",
        ),
        _tile(
            "En revisión",
            number(extras["review"], 0),
            f"{uf(extras['review_uf'])} presentados o en borrador",
            tone="warn" if extras["review"] else "neutral",
            icon="clock",
        ),
        _tile(
            "Sobre el contrato",
            _pct_text(extras["pct"]),
            "Monto aprobado sobre el contrato original",
            bar=min(100, extras["pct"]),
            icon="trending-up",
        ),
    ]


def rdi_tiles(rdi):
    pending = rdi["counts"]["pendiente"]
    if not pending:
        pending_hint = "No hay consultas esperando respuesta"
    elif rdi["overdue"]:
        pending_hint = (
            f"{_plural(rdi['overdue'], 'lleva', 'llevan')} más de 30 días · "
            f"la más antigua, {rdi['oldest']} días"
        )
    else:
        pending_hint = f"La más antigua lleva {_plural(rdi['oldest'], 'día', 'días')}"
    answered = rdi["counts"]["respondida"]
    average = rdi["average_days"]
    return [
        _tile(
            "Sin responder",
            number(pending, 0),
            pending_hint,
            tone="bad" if rdi["overdue"] else "warn" if pending else "ok",
            focal=True,
            size="lg",
            icon="message-circle-question",
            css="span-2",
        ),
        _tile(
            "Respuestas incompletas",
            number(rdi["counts"]["incompleta"], 0),
            "Requieren seguimiento con el mandante",
            tone="accent" if rdi["counts"]["incompleta"] else "neutral",
            icon="alert-triangle",
        ),
        _tile(
            "Respondidas",
            number(answered, 0),
            f"de {_plural(rdi['total'], 'consulta', 'consultas')}",
            bar=answered / rdi["total"] * 100 if rdi["total"] else 0,
            tone="ok",
            icon="circle-check",
        ),
        _tile(
            "Días promedio de respuesta",
            number(average, 1) if average is not None else "—",
            _plural(rdi["answered"], "respuesta con fecha", "respuestas con fecha"),
            icon="clock",
        ),
    ]


def photo_tiles(photos):
    return [
        _tile(
            "Fotos en la galería",
            number(photos["total"], 0),
            "Desde el inicio de la obra",
            tone="accent",
            focal=True,
            size="lg",
            icon="camera",
            css="span-2",
        ),
        _tile("Últimos 7 días", number(photos["week"], 0), "Incluye hoy", icon="calendar"),
        _tile(
            "Problemas y seguridad",
            number(photos["flagged"], 0),
            "Fotos etiquetadas para revisión",
            tone="warn" if photos["flagged"] else "neutral",
            icon="alert-triangle",
        ),
        _tile("Hoy", number(photos["today"], 0), "Subidas con fecha de hoy", icon="upload"),
    ]


def report_facts(summary, batch):
    total = summary["checklist"]["total"]
    state = summary["curves"][0]["state"] if summary["curves"] else None
    included = batch["included"]
    problems = sum(r["section"] == "problema" for r in included)
    pending = summary["pending"]
    facts = [
        dict(
            label="Cumplimiento PDR",
            value=_pct_text(total) if total is not None else "—",
            tone=compliance_tone(total),
            icon="shield-check",
        ),
        dict(
            label="Avance real / programado",
            value=(
                f"{_pct_text(state['real'] * 100)} / {_pct_text(state['programado'] * 100)}"
                if state
                else "—"
            ),
            tone="neutral",
            icon="activity",
        ),
        dict(
            label="Variación",
            value=_signed_pp(state["variacion"]) if state else "—",
            tone=progress_tone(state["variacion"] if state else None),
            icon="trending-up",
        ),
        dict(
            label="Dotación",
            value=_plural(summary["total_people"], "persona", "personas"),
            tone="neutral",
            icon="users",
        ),
        dict(
            label="RDI pendientes",
            value=number(pending, 0),
            tone="warn" if pending else "ok",
            icon="message-circle-question",
        ),
        dict(
            label="Fotos",
            value=_plural(len(included), "incluida", "incluidas"),
            hint=f"{problems} en posibles problemas" if problems else "",
            tone="neutral",
            icon="camera",
        ),
    ]
    return facts
