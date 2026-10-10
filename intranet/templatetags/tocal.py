from datetime import date, datetime

from django import template
from django.template.base import token_kwargs
from django.utils.html import format_html, json_script
from django.utils.safestring import mark_safe

register = template.Library()

TONES = ("neutral", "accent", "ambar", "ok", "warn", "bad")
STATUS_DOTS = {
    "pendiente": "warn",
    "respondida": "ok",
    "aprobado": "ok",
    "cumple": "ok",
    "ok": "ok",
    "emitido": "ok",
    "incompleta": "naranjo",
    "presentado": "sky",
    "adelanto": "sky",
    "facturado": "verde",
    "pagado": "verde-oscuro",
    "rechazado": "bad",
    "no_cumple": "bad",
    "atraso": "bad",
    "borrador": "gris",
    "no_aplica": "gris",
}
RUBROS = ("energia", "industrial", "comercial", "educacional", "urbanizacion", "otros")
RUBRO_NAMES = {
    "energia": "Energía",
    "industrial": "Industrial",
    "comercial": "Comercial",
    "educacional": "Educacional",
    "urbanizacion": "Urbanización",
    "otros": "Otros",
}
DOC_TYPES = {
    "factura": "Factura",
    "factura_electronica": "Factura electrónica",
    "nota_credito": "Nota de crédito",
    "exenta": "Exenta",
}
MODULE_ICONS = {
    "resumen": "layout-dashboard",
    "pdr": "hard-hat",
    "avance": "activity",
    "edp": "receipt",
    "adicionales": "file-plus",
    "rdi": "message-circle-question",
    "fotos": "camera",
    "informes": "file-text",
}
CARD_OPTIONS = {"title", "description", "eyebrow", "tone", "flush", "id", "title_id", "css"}


@register.filter
def number(value, places=2):
    if value is None or value == "":
        return "—"
    try:
        return (
            f"{float(value):,.{int(places)}f}".replace(",", "_").replace(".", ",").replace("_", ".")
        )
    except (ValueError, TypeError):
        return value


@register.filter
def pct(value):
    return "—" if value is None else number(float(value) * 100, 1) + " %"


@register.filter
def item(obj, key):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    if value is None or value == "":
        return "—"
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, float):
        return number(value)
    if key in ("estado", "status", "rubro", "tipo_documento"):
        return str(value).replace("_", " ").capitalize()
    return value


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    query = context["request"].GET.copy()
    query.update(kwargs)
    return query.urlencode()


@register.filter
def pct0(value):
    return "—" if value in (None, "") else number(float(value) * 100, 0) + " %"


@register.filter
def percent_value(value):
    return float(value or 0) * 100


@register.filter
def uf(value, places=2):
    return "UF " + str(number(value, places))


@register.filter
def clp(value):
    return "$ " + str(number(value, 0))


@register.filter
def clpm(value):
    return "$ " + str(number(float(value or 0) / 1e6, 1)) + " M"


@register.filter
def clp_short(value):
    return clpm(value) if abs(float(value or 0)) >= 1e6 else clp(value or 0)


@register.filter
def doc_type(value):
    return DOC_TYPES.get(value, str(value or "").replace("_", " ").capitalize())


@register.filter
def rubro_name(value):
    return RUBRO_NAMES.get(value, str(value or "").capitalize())


@register.simple_tag
def money(value, css=""):
    """Recibe los textos de ambas monedas: {"uf": "UF 1.234", "clp": "$ 1,2 M"}."""
    return format_html(
        '<span class="money{}" data-uf="{}" data-clp="{}">{}</span>',
        f" {css}" if css else "",
        value["uf"],
        value["clp"],
        value["uf"],
    )


@register.filter
def initials(value):
    return "".join(p[0].upper() for p in str(value).split()[:2])


def _clamp_percent(value):
    try:
        return max(0.0, min(100.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _tone(tone):
    return tone if tone in TONES else "neutral"


@register.simple_tag
def icon(name, size=None, label="", css=""):
    """Uso: {% icon "camera" size=20 label="Fotos" %}."""
    size_style = format_html(' style="width:{}px;height:{}px"', size, size) if size else ""
    a11y = (
        format_html(' role="img" aria-label="{}"', label)
        if label
        else mark_safe(' aria-hidden="true"')
    )
    return format_html(
        '<svg class="icon{}"{}{} focusable="false"><use href="#i-{}"></use></svg>',
        f" {css}" if css else "",
        size_style,
        a11y,
        name,
    )


@register.filter
def module_icon(slug):
    return MODULE_ICONS.get(slug, "file-text")


@register.simple_tag
def progress_ring(value, size=56, tone="accent", label="", stroke=None):
    """value debe estar entre 0 y 100; label aparece en el centro."""
    value = _clamp_percent(value)
    size = int(size)
    stroke = float(stroke or max(4, round(size / 10)))
    radius = (size - stroke) / 2
    center = size / 2
    return format_html(
        '<span class="ring tone-{}{}" style="--size:{}px;--offset:{}">'
        '<svg viewBox="0 0 {} {}" aria-hidden="true" focusable="false">'
        '<circle class="ring__track" cx="{}" cy="{}" r="{}" stroke-width="{}"/>'
        '<circle class="ring__bar" cx="{}" cy="{}" r="{}" stroke-width="{}" pathLength="100"/>'
        '</svg><span class="ring__label">{}</span></span>',
        _tone(tone),
        " is-empty" if value == 0 else "",
        size,
        f"{100 - value:.2f}",
        size,
        size,
        center,
        center,
        radius,
        stroke,
        center,
        center,
        radius,
        stroke,
        label,
    )


@register.inclusion_tag("intranet/components/stat_tile.html")
def stat_tile(
    label,
    value,
    hint="",
    tone="neutral",
    ring=None,
    bar=None,
    focal=False,
    size="md",
    icon="",
    ring_label="",
    css="",
):
    """ring y bar van de 0 a 100; focal destaca la tarjeta."""
    return {
        "label": label,
        "value": value,
        "hint": hint,
        "tone": _tone(tone),
        "ring": None if ring is None or ring == "" else _clamp_percent(ring),
        "ring_size": 84 if size == "lg" else 56,
        "ring_label": ring_label,
        "bar": None if bar is None or bar == "" else _clamp_percent(bar),
        "focal": focal,
        "size": "lg" if size == "lg" else "md",
        "icon": icon,
        "css": css,
    }


@register.simple_tag
def status_badge(estado, label=None):
    key = str(estado or "")
    text = label if label not in (None, "") else key.replace("_", " ").capitalize() or "—"
    return format_html(
        '<span class="badge" data-estado="{}"><i class="dot dot-{}" aria-hidden="true"></i>{}</span>',
        key,
        STATUS_DOTS.get(key, "gris"),
        text,
    )


@register.simple_tag
def rubro_badge(rubro, label=None):
    key = rubro if rubro in RUBROS else "otros"
    if label in (None, ""):
        label = RUBRO_NAMES.get(rubro) or str(rubro or "otros").capitalize()
    return format_html(
        '<span class="badge"><i class="dot dot-{}" aria-hidden="true"></i>{}</span>', key, label
    )


@register.inclusion_tag("intranet/components/empty_state.html")
def empty_state(title, text="", icon="inbox"):
    return {"title": title, "text": text, "icon": icon}


class CardActionsNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        return self.nodelist.render(context)


class SectionCardNode(template.Node):
    def __init__(self, nodelist, options):
        self.nodelist = nodelist
        self.options = options

    def render(self, context):
        options = {key: value.resolve(context) for key, value in self.options.items()}
        actions, body = [], []
        for node in self.nodelist:
            target = actions if isinstance(node, CardActionsNode) else body
            target.append(node.render_annotated(context))
        card = context.template.engine.get_template("intranet/components/section_card.html")
        with context.push(
            card=options,
            card_actions=mark_safe("".join(actions).strip()),
            card_body=mark_safe("".join(body)),
        ):
            return card.render(context)


@register.tag("card_actions")
def do_card_actions(parser, token):
    nodelist = parser.parse(("endcard_actions",))
    parser.delete_first_token()
    return CardActionsNode(nodelist)


@register.tag("section_card")
def do_section_card(parser, token):
    bits = token.split_contents()
    options = token_kwargs(bits[1:], parser)
    if len(options) != len(bits) - 1:
        raise template.TemplateSyntaxError("section_card solo acepta argumentos con nombre.")
    unknown = set(options) - CARD_OPTIONS
    if unknown:
        raise template.TemplateSyntaxError(f"section_card no reconoce: {', '.join(unknown)}")
    nodelist = parser.parse(("endsection_card",))
    parser.delete_first_token()
    return SectionCardNode(nodelist, options)


@register.simple_tag
def chart(kind, data, id, height=280, label="", zoom=False, moneda="", variant="", css=""):
    """Uso: {% chart "curva-s" datos id="avance" height=320 zoom=True %}.
    El resumen accesible se toma de label o de data.summary."""
    data = data or {}
    summary = label or data.get("summary") or "Gráfico"
    source = f"{id}-data"
    attrs = format_html(
        ' data-chart="{}" data-source="{}" style="--chart-h:{}px" role="img" aria-label="{}"',
        kind,
        source,
        int(height),
        summary,
    )
    for name, value in (("data-moneda", moneda), ("data-variant", variant)):
        if value:
            attrs += format_html(' {}="{}"', name, value)
    if zoom:
        attrs += mark_safe(" data-zoom")
    return format_html(
        '<div class="chart{}" id="{}"{}></div>{}<noscript><p class="chart__summary">{}</p></noscript>',
        f" {css}" if css else "",
        id,
        attrs,
        json_script(data, source),
        summary,
    )
