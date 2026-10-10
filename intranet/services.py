import base64
import io
from datetime import datetime, timedelta

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from . import models as m
from . import private_storage as storage
from .calculations import (
    batch_start,
    compliance,
    curve_state,
    monthly_safety,
    payment_summary,
    staffing,
)

register_heif_opener()


def private_path(key):
    root = settings.MEDIA_ROOT.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValidationError("Ruta de archivo inválida.")
    return path


@transaction.atomic
def create_week(obra):
    # Bloquea la obra para evitar números de semana duplicados, incluso al crear la primera.
    m.Obra.objects.select_for_update().get(pk=obra.pk)
    previous = m.Semana.objects.filter(obra=obra).order_by("-numero").first()
    start = previous.fecha_fin + timedelta(days=1) if previous else obra.inicio_contrato
    return m.Semana.objects.create(
        obra=obra,
        numero=previous.numero + 1 if previous else 1,
        fecha_inicio=start,
        fecha_fin=start + timedelta(days=6),
    )


def checklist_for(week):
    evaluation = m.ChecklistEvaluacion.objects.filter(semana=week).first()
    inherited = False
    if not evaluation:
        evaluation = (
            m.ChecklistEvaluacion.objects.filter(
                semana__obra=week.obra, semana__numero__lt=week.numero
            )
            .order_by("-semana__numero")
            .first()
        )
        inherited = bool(evaluation)
    answers = (
        {r.item_id: r for r in m.ChecklistRespuesta.objects.filter(evaluacion=evaluation)}
        if evaluation
        else {}
    )
    rows = []
    for item in m.ChecklistItem.objects.filter(activo=True).order_by("orden"):
        answer = answers.get(item.pk)
        rows.append(
            dict(
                item=item,
                categoria=item.categoria,
                estado=answer.estado if answer else "cumple",
                observacion=answer.observacion if answer else "",
            )
        )
    return dict(
        rows=rows,
        inherited=inherited,
        evaluado_por=evaluation.evaluado_por if evaluation else "",
        **compliance(rows),
    )


def staffing_for(obra, week=None):
    query = (
        m.Dotacion.objects.filter(semana__obra=obra)
        .select_related("semana")
        .order_by("semana__numero")
    )
    if week:
        query = query.filter(semana__numero__lte=week.numero)
    return staffing(
        [
            {
                **{
                    f.name: getattr(d, f.name) for f in m.Dotacion._meta.fields if not f.is_relation
                },
                "numero": d.semana.numero,
                "fecha_inicio": d.semana.fecha_inicio,
                "fecha_fin": d.semana.fecha_fin,
            }
            for d in query
        ]
    )


def curves_for(obra, cutoff=None, svg=True):
    """Usa svg=False en pantalla; el SVG se genera solo para el PDF."""
    curves = list(m.Curva.objects.filter(obra=obra).order_by("orden"))
    points = m.PuntoCurva.objects.filter(curva__in=curves).order_by("semana")
    if cutoff:
        points = points.filter(fecha__lte=cutoff)
    grouped = {c.pk: [] for c in curves}
    for p in points.values():
        grouped[p["curva_id"]].append(p)
    result = []
    for c in curves:
        ps = grouped[c.pk]
        result.append(
            dict(
                curve=c,
                points=ps,
                state=curve_state(ps, c.dias_habiles_programa),
                svg=curve_svg(ps) if svg else None,
            )
        )
    return result


def main_curve_states(obras):
    main = {}
    for c in m.Curva.objects.filter(obra__in=obras).order_by("obra_id", "orden"):
        main.setdefault(c.obra_id, c)
    points = {c.pk: [] for c in main.values()}
    for p in m.PuntoCurva.objects.filter(curva__in=main.values()).values():
        points[p["curva_id"]].append(p)
    return {
        obra_id: curve_state(points[c.pk], c.dias_habiles_programa) for obra_id, c in main.items()
    }


def obra_rubros(obras):
    rows = (
        m.Venta.objects.filter(obra_ref__in=obras)
        .values("obra_ref_id", "rubro")
        .annotate(total=Count("pk"))
        .order_by("obra_ref_id", "-total", "rubro")
    )
    rubros = {}
    for row in rows:
        rubros.setdefault(row["obra_ref_id"], row["rubro"])
    return rubros


def curve_svg(points):
    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    width, height, left, top = 740, 250, 45, 15

    def x(i):
        return left + i / max(1, len(points) - 1) * (width - left - 20)

    def y(v):
        return top + (1 - v) * (height - top - 35)

    chunks = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Curva S de avance" class="curve">'
    ]
    for n in (0, 0.25, 0.5, 0.75, 1):
        chunks.append(
            f'<line x1="45" x2="720" y1="{y(n)}" y2="{y(n)}" stroke="#e9e5de"/><text x="3" y="{y(n) + 4}" fill="#777" font-size="11">{n * 100:.0f}%</text>'
        )
    for key, color in [("programado", "#8a94a6"), ("real", "#e77825"), ("reprogramado", "#35a183")]:
        segments = []
        current = []
        for i, p in enumerate(points):
            if p[key] is None:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(f"{x(i):.2f},{y(p[key]):.2f}")
        if current:
            segments.append(current)
        for segment in segments:
            chunks.append(
                f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="3"/>'
            )
    if points:
        chunks.append(
            f'<text x="45" y="245" font-size="11" fill="#777">{escape(str(points[0]["fecha"]))}</text><text x="640" y="245" font-size="11" fill="#777">{escape(str(points[-1]["fecha"]))}</text>'
        )
    return mark_safe("".join(chunks) + "</svg>")


def report_photos(report):
    previous = (
        m.Informe.objects.filter(obra=report.obra, fecha_corte__lt=report.fecha_corte)
        .order_by("-fecha_corte")
        .first()
    )
    start = batch_start(
        report.fecha_corte, report.semana.fecha_inicio, previous.fecha_corte if previous else None
    )
    overrides = {x.foto_id: x for x in m.InformeFoto.objects.filter(informe=report)}
    rows = []
    for photo in m.Foto.objects.filter(obra=report.obra).order_by("fecha", "created_at"):
        override = overrides.get(photo.pk)
        in_batch = start <= photo.fecha <= report.fecha_corte
        included = override.incluir if override else in_batch
        section = (override.seccion if override else None) or (
            "problema" if photo.etiqueta == "problema" else "obra"
        )
        rows.append(
            dict(
                photo=photo,
                included=included,
                forced=included and not in_batch,
                section=section,
                order=(override.orden or 0) if override else 0,
                in_batch=in_batch,
            )
        )
    rows.sort(key=lambda r: (r["order"], r["photo"].fecha, r["photo"].created_at))
    return dict(
        start=start, end=report.fecha_corte, all=rows, included=[r for r in rows if r["included"]]
    )


def report_photo_counts(obra, reports):
    """Cuenta las fotos con la misma regla que report_photos, sin consultas por informe."""
    cutoffs = sorted({r.fecha_corte for r in reports})
    photos = list(m.Foto.objects.filter(obra=obra).values_list("pk", "fecha"))
    overrides = {}
    for informe_id, foto_id, incluir in m.InformeFoto.objects.filter(
        informe__in=reports
    ).values_list("informe_id", "foto_id", "incluir"):
        overrides.setdefault(informe_id, {})[foto_id] = incluir
    counts = {}
    for report in reports:
        previous = max((c for c in cutoffs if c < report.fecha_corte), default=None)
        start = batch_start(report.fecha_corte, report.semana.fecha_inicio, previous)
        chosen = overrides.get(report.pk, {})
        counts[report.pk] = sum(
            chosen.get(pk, start <= fecha <= report.fecha_corte) for pk, fecha in photos
        )
    return counts


def obra_summary(obra, week=None, cutoff=None, svg=True):
    series = staffing_for(obra, week)
    latest = week or m.Semana.objects.filter(obra=obra).order_by("-numero").first()
    checks = checklist_for(latest) if latest else dict(rows=[], categories=[], total=None)
    edp = list(m.EstadoPago.objects.filter(obra=obra).order_by("numero"))
    extras = list(m.Adicional.objects.filter(obra=obra).order_by("numero"))
    queries = list(m.Rdi.objects.filter(obra=obra).order_by("numero"))
    for r in queries:
        r.days_open = ((r.fecha_respuesta or timezone.localdate()) - r.fecha_envio).days
    return dict(
        obra=obra,
        series=series,
        last_staff=series[-1] if series else None,
        checklist=checks,
        safety=monthly_safety(series),
        curves=curves_for(obra, cutoff, svg=svg),
        edp=edp,
        payments=payment_summary(
            obra.monto_contractual_uf,
            [{"monto_uf": p.monto_uf, "estado": p.estado} for p in edp],
            obra.anticipo_uf,
        ),
        extras=extras,
        extras_total=sum(a.monto_uf or 0 for a in extras if a.estado == "aprobado"),
        queries=queries,
        pending=sum(r.estado == "pendiente" for r in queries),
        oldest_pending=max((r.days_open for r in queries if r.estado == "pendiente"), default=0),
        latest_report=m.Informe.objects.filter(obra=obra).order_by("-fecha_corte").first(),
        total_people=(series[-1]["total_personal"] + series[-1]["personal_sc"]) if series else 0,
        week=latest,
    )


def report_context(report, embed=False):
    data = obra_summary(report.obra, report.semana, report.fecha_corte)
    photos = report_photos(report)
    for row in photos["included"]:
        row["url"] = "/api/files/" + row["photo"].storage_path
        if embed:
            try:
                raw = storage.read_bytes(row["photo"].storage_path)
            except (FileNotFoundError, httpx.HTTPError) as exc:
                raise ValidationError("Falta una fotografía del informe: " + row["photo"].storage_path) from exc
            row["url"] = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    data.update(
        report=report,
        photo_batch=photos,
        problem_photos=[r for r in photos["included"] if r["section"] == "problema"],
        work_photos=[r for r in photos["included"] if r["section"] == "obra"],
    )
    logo = settings.BASE_DIR / "pdf-assets/logo-tocal.png"
    data["logo"] = "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode()
    return data


def generate_pdf(report):
    from weasyprint import HTML, default_url_fetcher

    # El PDF solo puede cargar los recursos embebidos que genera esta función.
    def fetch(url, *args, **kwargs):
        if not url.startswith("data:"):
            raise ValueError("Recurso externo no permitido en el PDF.")
        return default_url_fetcher(url, *args, **kwargs)

    html = render_to_string("intranet/report_document.html", report_context(report, embed=True))
    return HTML(string=html, url_fetcher=fetch).write_pdf()


def upload_photos(obra, user, files, values):
    if not files:
        raise ValidationError("Selecciona al menos una imagen.")
    if len(files) > 30:
        raise ValidationError("Sube hasta 30 fotos a la vez.")
    prepared = []
    for file in files:
        if file.size > 25 * 1024 * 1024:
            raise ValidationError(f"{file.name} supera 25 MB.")
        try:
            with Image.open(file) as image:
                exif = image.getexif()
                date_text = exif.get(36867) or exif.get(306)
                try:
                    date_text = date_text or exif.get_ifd(0x8769).get(36867)
                except (KeyError, TypeError):
                    pass
                try:
                    captured = datetime.strptime(str(date_text), "%Y:%m:%d %H:%M:%S").date()
                except ValueError:
                    captured = values.get("fecha") or timezone.localdate()
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1800, 1800))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=82, optimize=True)
                photo = m.Foto(
                    obra=obra,
                    subido_por=user,
                    fecha=captured,
                    etiqueta=values["etiqueta"],
                    sector=values.get("sector"),
                    ancho=image.width,
                    alto=image.height,
                )
                photo.storage_path = f"obras/{obra.pk}/fotos/{photo.pk}.jpg"
                prepared.append((photo, output.getvalue()))
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValidationError(f"No se pudo leer la imagen {file.name}.") from exc
    written = []
    try:
        with transaction.atomic():
            for photo, data in prepared:
                storage.write_bytes(photo.storage_path, data, "image/jpeg")
                written.append(photo.storage_path)
                photo.save()
    except Exception:
        for key in written:
            try:
                storage.delete(key)
            except Exception:
                pass  # La limpieza de objetos huérfanos se puede reintentar.
        raise
    return [p for p, _ in prepared]


def uf_for_date(day):
    from django.core.cache import cache

    key = f"uf:{day.isoformat()}"
    value = cache.get(key)
    if value is not None:
        return value
    try:
        response = httpx.get(f"https://mindicador.cl/api/uf/{day:%d-%m-%Y}", timeout=8)
        response.raise_for_status()
        value = float(response.json()["serie"][0]["valor"])
        if value > 0:
            cache.set(key, value, 86400)
            return value
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        pass
    return None
