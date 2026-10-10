import math

from django import forms
from django.core.exceptions import ValidationError

from . import models as m
from .calculations import sales_amounts
from .templatetags.tocal import DOC_TYPES, RUBRO_NAMES

LABELS = {
    "personal_operativo": "Personal operativo",
    "personal_adm": "Personal administrativo",
    "hh_operativas": "HH operativas",
    "hh_adm": "HH administrativas",
    "personal_sc": "Personal subcontrato",
    "hh_sc": "HH subcontrato",
    "dotacion_femenina": "Dotación femenina",
    "permisos_licencias": "Permisos y licencias",
    "subcontratos": "N° de subcontratos",
    "accidentes": "Accidentes (trabajo y trayecto)",
    "dias_perdidos": "Días perdidos",
    "rut_cliente": "Cliente (RUT)",
    "razon_social": "Razón social",
    "numero": "N°",
    "afecto": "Neto $ (afecto)",
    "uf_dia": "UF del día",
    "tipo_documento": "Tipo de documento",
    "monto_uf": "Monto UF",
    "pct_programa": "Avance programado (%)",
    "pct_actual": "Avance real (%)",
    "programado": "Programado (%)",
    "real": "Real (%)",
    "reprogramado": "Reprogramado (%)",
    "caption": "Descripción de la foto",
    "monto_aprobado_uf": "Monto aprobado UF",
    "numero_factura": "N° de factura",
    "numero_oc": "N° de orden de compra",
    "fecha_presentacion": "Fecha de presentación",
    "fecha_envio": "Fecha de envío",
    "fecha_respuesta": "Fecha de respuesta",
    "respondida_por": "Respondida por",
    "periodo": "Período",
    "clasificacion": "Clasificación",
    "descripcion": "Descripción",
    "observacion": "Observación",
}

HELP = {
    "periodo": "Por ejemplo: marzo 2026.",
    "monto_aprobado_uf": "Lo que aprobó el mandante. Si queda vacío, se considera el monto presentado.",
    "medio": "Correo, libro de obra, reunión u otro.",
    "fecha_respuesta": "Obligatoria si la consulta está respondida o incompleta.",
    "responsable": "Quién debe responder en el mandante.",
    "sector": "Por ejemplo: losa eje 3, patio de estanques.",
}


class WholeNumberInput(forms.NumberInput):
    def format_value(self, value):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return super().format_value(value)


class DomainForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.label = LABELS.get(name, field.label)
            field.help_text = field.help_text or HELP.get(name, "")
            if isinstance(field, forms.DateField):
                field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            elif isinstance(field.widget, forms.Textarea):
                if name not in ("comentarios", "posibles_problemas"):
                    field.widget = (
                        forms.TextInput()
                        if name
                        not in ("observacion", "observaciones", "razon_accion", "nota_avance")
                        else forms.Textarea(attrs={"rows": 3})
                    )
            if isinstance(field, forms.FloatField) and type(field.widget) is forms.NumberInput:
                field.widget = WholeNumberInput(attrs=field.widget.attrs)
            if isinstance(field, (forms.IntegerField, forms.FloatField)):
                field.widget.attrs["min"] = 0

    def clean(self):
        data = super().clean()
        for name, value in list(data.items()):
            if isinstance(value, (float, int)) and (
                not math.isfinite(value) or (value < 0 and name not in ("afecto", "orden"))
            ):
                self.add_error(name, "Ingresa un número válido, mayor o igual a cero.")
        if data.get("numero") is not None and data["numero"] < 1:
            self.add_error("numero", "Debe ser mayor que cero.")
        return data


class DotacionForm(DomainForm):
    class Meta:
        model = m.Dotacion
        exclude = ("id", "semana", "updated_at")

    def clean(self):
        d = super().clean()
        if d.get("dotacion_femenina", 0) > d.get("personal_operativo", 0) + d.get(
            "personal_adm", 0
        ):
            self.add_error("dotacion_femenina", "No puede superar la dotación Tocal.")
        return d


DOTACION_GROUPS = [
    ("Personal Tocal", ("personal_operativo", "personal_adm", "dotacion_femenina")),
    ("Movimientos", ("permisos_licencias", "ingresos", "finiquitos")),
    ("Horas hombre", ("hh_operativas", "hh_adm")),
    ("Subcontratos", ("subcontratos", "personal_sc", "hh_sc")),
    ("Seguridad", ("incidentes", "accidentes", "dias_perdidos")),
]


class PercentForm(DomainForm):
    percent_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key in self.percent_fields:
            self.fields[key] = forms.FloatField(
                required=False,
                min_value=0,
                max_value=100,
                label=LABELS.get(key, key),
                widget=forms.NumberInput(attrs={"step": "0.01"}),
            )
            val = self.initial.get(key)
            if val is not None:
                self.initial[key] = val * 100

    def clean(self):
        d = super().clean()
        for key in self.percent_fields:
            if d.get(key) is not None:
                d[key] /= 100
        return d


class PuntoForm(PercentForm):
    percent_fields = ("programado", "real", "reprogramado")

    class Meta:
        model = m.PuntoCurva
        fields = ("semana", "fecha", "programado", "real", "reprogramado")

    def clean_semana(self):
        value = self.cleaned_data["semana"]
        if value < 1:
            raise ValidationError("La semana debe ser mayor que cero.")
        return value


class ActividadForm(PercentForm):
    percent_fields = ("pct_programa", "pct_actual")

    class Meta:
        model = m.Actividad
        fields = ("pct_programa", "pct_actual", "status", "razon_accion")

    def clean(self):
        d = super().clean()
        if (
            not d.get("status")
            and d.get("pct_programa") is not None
            and d.get("pct_actual") is not None
        ):
            delta = d["pct_actual"] - d["pct_programa"]
            d["status"] = "atraso" if delta < -1e-9 else "adelanto" if delta > 1e-9 else "ok"
        return d


class EdpForm(DomainForm):
    class Meta:
        model = m.EstadoPago
        exclude = ("id", "obra")


class AdicionalForm(DomainForm):
    class Meta:
        model = m.Adicional
        exclude = ("id", "obra")


class RdiForm(DomainForm):
    class Meta:
        model = m.Rdi
        exclude = ("id", "obra")

    def clean(self):
        d = super().clean()
        if d.get("estado") == "pendiente":
            d["fecha_respuesta"] = None
        elif not d.get("fecha_respuesta"):
            self.add_error("fecha_respuesta", "Indica la fecha de respuesta.")
        if (
            d.get("fecha_respuesta")
            and d.get("fecha_envio")
            and d["fecha_respuesta"] < d["fecha_envio"]
        ):
            self.add_error("fecha_respuesta", "No puede ser anterior al envío.")
        return d


def validate_bullets(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValidationError("Ingresa una lista de hasta 100 viñetas.")
    for b in value:
        if (
            not isinstance(b, dict)
            or not isinstance(b.get("texto"), str)
            or not 1 <= len(b["texto"].strip()) <= 1000
        ):
            raise ValidationError("Cada viñeta necesita un texto de 1 a 1000 caracteres.")
        if "destacado" in b and not isinstance(b["destacado"], bool):
            raise ValidationError("Destacado debe ser verdadero o falso.")
        subs = b.get("sub", [])
        if not isinstance(subs, list) or any(
            not isinstance(s, str) or not 1 <= len(s.strip()) <= 500 for s in subs
        ):
            raise ValidationError("Revisa las subviñetas.")
    return value


class BulletField(forms.CharField):
    widget = forms.Textarea(attrs={"rows": 9})

    def prepare_value(self, value):
        if isinstance(value, list):
            lines = []
            for b in value:
                lines.append(("! " if b.get("destacado") else "") + b["texto"])
                lines.extend("  - " + s for s in b.get("sub", []))
            return "\n".join(lines)
        return value

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, list):
            return validate_bullets(value)
        bullets = []
        for line in value.splitlines():
            if not line.strip():
                continue
            if line.startswith("  - ") and bullets:
                bullets[-1].setdefault("sub", []).append(line[4:].strip())
            else:
                text = line.strip()
                bullets.append(
                    {
                        "texto": text[2:] if text.startswith("! ") else text,
                        "destacado": text.startswith("! "),
                    }
                )
        return validate_bullets(bullets)


class InformeForm(DomainForm):
    comentarios = BulletField(
        required=False,
        label="2.1 Comentarios",
        help_text="Una viñeta por línea. Usa ! al inicio para destacar y dos espacios + - para una subviñeta.",
    )
    posibles_problemas = BulletField(required=False, label="2.2 Posibles problemas")

    class Meta:
        model = m.Informe
        fields = ("titulo", "fecha_corte", "nota_avance", "comentarios", "posibles_problemas")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].label = "Título"
        self.fields["fecha_corte"].label = "Fecha de corte"
        self.fields["nota_avance"].label = "Nota de avance"
        self.fields["nota_avance"].help_text = "Aparece bajo la curva S del informe."
        # Los campos de distintas tarjetas pertenecen al mismo formulario.
        for field in self.fields.values():
            field.widget.attrs["form"] = "report-form"


class FotoForm(DomainForm):
    class Meta:
        model = m.Foto
        fields = ("fecha", "etiqueta", "sector", "caption")


class UploadForm(forms.Form):
    etiqueta = forms.ChoiceField(choices=m.Foto._meta.get_field("etiqueta").choices)
    sector = forms.CharField(max_length=80, required=False, help_text=HELP["sector"])
    fecha = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Fecha",
        help_text="Se usa solo si la foto no trae la fecha de toma.",
    )

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class FotoOverrideForm(forms.ModelForm):
    class Meta:
        model = m.InformeFoto
        fields = ("incluir", "seccion", "orden")


class VentaForm(DomainForm):
    uf_dia = forms.FloatField(
        required=False,
        min_value=0.0001,
        label="UF del día",
        help_text="Si queda vacío, se consultará la UF de la fecha indicada.",
    )

    class Meta:
        model = m.Venta
        fields = (
            "tipo_documento",
            "numero",
            "fecha",
            "rut_cliente",
            "razon_social",
            "rubro",
            "obra",
            "afecto",
            "uf_dia",
            "observacion",
        )

    def __init__(self, *args, fetch_uf=True, **kwargs):
        self.fetch_uf = fetch_uf
        super().__init__(*args, **kwargs)
        self.fields["afecto"].widget.attrs.pop("min", None)
        # Conserva los valores del modelo; agrega tildes solo a las etiquetas.
        self.fields["tipo_documento"].choices = list(DOC_TYPES.items())
        self.fields["rubro"].choices = list(RUBRO_NAMES.items())

    def clean_rut_cliente(self):
        value = self.cleaned_data["rut_cliente"].upper().replace(".", "").strip()
        if not 7 <= len(value) <= 12:
            raise ValidationError("Revisa el RUT.")
        return value

    def clean(self):
        d = super().clean()
        if not d.get("uf_dia") and d.get("fecha") and self.fetch_uf:
            from .services import uf_for_date

            d["uf_dia"] = uf_for_date(d["fecha"])
        if not d.get("uf_dia"):
            self.add_error("uf_dia", "No se pudo obtener la UF; ingrésala manualmente.")
        if all(d.get(k) for k in ("tipo_documento", "numero", "rut_cliente")):
            dup = m.Venta.objects.filter(
                tipo_documento=d["tipo_documento"], numero=d["numero"], rut_cliente=d["rut_cliente"]
            ).exclude(pk=self.instance.pk)
            if dup.exists() and (
                self.instance._state.adding
                or any(k in self.changed_data for k in ("tipo_documento", "numero", "rut_cliente"))
            ):
                self.add_error("numero", "Ya existe este documento para el cliente.")
        return d

    def save(self, commit=True):
        obj = super().save(commit=False)
        for k, v in sales_amounts(obj.tipo_documento, obj.afecto, obj.uf_dia).items():
            setattr(obj, k, v)
        if commit:
            obj.save()
        return obj
