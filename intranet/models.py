from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


def new_id():
    return str(uuid4())


class User(AbstractUser):
    id = models.CharField(primary_key=True, max_length=64, default=new_id, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200)
    rol = models.CharField(
        max_length=20,
        choices=[
            ("gerencia", "Gerencia"),
            ("admin_obra", "Administrador de obra"),
            ("experto_pdr", "Experto PDR"),
            ("lectura", "Solo lectura"),
        ],
        default="lectura",
    )
    legacy_password = models.TextField(blank=True)

    def __str__(self):
        return self.name or self.email


class Record(models.Model):
    id = models.CharField(primary_key=True, max_length=64, default=new_id, editable=False)

    class Meta:
        abstract = True


class Obra(Record):
    nombre = models.TextField()
    razon_social = models.TextField()
    rut = models.TextField()
    servicio = models.TextField()
    direccion = models.TextField(null=True, blank=True)
    mandante = models.TextField(null=True, blank=True)
    inicio_contrato = models.DateField()
    termino_contrato = models.DateField(null=True, blank=True)
    asesor_pdr = models.TextField(null=True, blank=True)
    asesor_mutual = models.TextField(null=True, blank=True)
    adm_contrato = models.TextField(null=True, blank=True)
    monto_contractual_uf = models.FloatField(default=0)
    anticipo_uf = models.FloatField(default=0)
    fecha_programa_aprobado = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_obras"

    def __str__(self):
        return str(self.nombre)


class ObraUsuario(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="+", db_column="user_id"
    )

    class Meta:
        db_table = "tocal_obra_usuarios"
        unique_together = [("obra", "user")]

    def __str__(self):
        return str(self.pk)


class Semana(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    numero = models.IntegerField()
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    class Meta:
        db_table = "tocal_semanas_obra"
        unique_together = [("obra", "numero")]

    def __str__(self):
        return str(self.pk)


class Dotacion(Record):
    semana = models.OneToOneField(
        "Semana", on_delete=models.CASCADE, related_name="+", db_column="semana_id"
    )
    personal_operativo = models.IntegerField(default=0)
    personal_adm = models.IntegerField(default=0)
    permisos_licencias = models.IntegerField(default=0)
    ingresos = models.IntegerField(default=0)
    finiquitos = models.IntegerField(default=0)
    hh_operativas = models.FloatField(default=0)
    hh_adm = models.FloatField(default=0)
    subcontratos = models.IntegerField(default=0)
    personal_sc = models.IntegerField(default=0)
    hh_sc = models.FloatField(default=0)
    incidentes = models.IntegerField(default=0)
    accidentes = models.IntegerField(default=0)
    dias_perdidos = models.IntegerField(default=0)
    dotacion_femenina = models.IntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_dotacion_semanal"

    def __str__(self):
        return str(self.pk)


class ChecklistItem(Record):
    categoria = models.CharField(
        max_length=40,
        choices=[
            ("antecedentes_generales", "Antecedentes generales"),
            ("antecedentes_legales", "Antecedentes legales"),
            ("sso_medio_ambiente", "Sso medio ambiente"),
            ("terreno", "Terreno"),
        ],
    )
    codigo = models.TextField(unique=True)
    subseccion = models.TextField(null=True, blank=True)
    descripcion = models.TextField()
    orden = models.IntegerField()
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "tocal_checklist_items"

    def __str__(self):
        return str(self.descripcion)


class ChecklistEvaluacion(Record):
    semana = models.OneToOneField(
        "Semana", on_delete=models.CASCADE, related_name="+", db_column="semana_id"
    )
    evaluado_por = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_checklist_evaluaciones"

    def __str__(self):
        return str(self.pk)


class ChecklistRespuesta(Record):
    evaluacion = models.ForeignKey(
        "ChecklistEvaluacion", on_delete=models.CASCADE, related_name="+", db_column="evaluacion_id"
    )
    item = models.ForeignKey(
        "ChecklistItem", on_delete=models.CASCADE, related_name="+", db_column="item_id"
    )
    estado = models.CharField(
        max_length=40,
        choices=[("cumple", "Cumple"), ("no_cumple", "No cumple"), ("no_aplica", "No aplica")],
        default="cumple",
    )
    observacion = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tocal_checklist_respuestas"
        unique_together = [("evaluacion", "item")]

    def __str__(self):
        return str(self.pk)


class Curva(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    variante = models.CharField(
        max_length=40,
        choices=[("general", "General"), ("ruta_critica", "Ruta critica"), ("accesos", "Accesos")],
    )
    nombre = models.TextField()
    descripcion = models.TextField(null=True, blank=True)
    orden = models.IntegerField(default=0)
    dias_habiles_programa = models.IntegerField(default=151)

    class Meta:
        db_table = "tocal_curvas_s"
        unique_together = [("obra", "variante")]

    def __str__(self):
        return str(self.nombre)


class PuntoCurva(Record):
    curva = models.ForeignKey(
        "Curva", on_delete=models.CASCADE, related_name="+", db_column="curva_id"
    )
    semana = models.IntegerField()
    fecha = models.DateField()
    programado = models.FloatField(null=True, blank=True)
    real = models.FloatField(null=True, blank=True)
    reprogramado = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "tocal_puntos_curva"
        unique_together = [("curva", "semana")]

    def __str__(self):
        return str(self.pk)


class Actividad(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    orden = models.IntegerField()
    nivel = models.IntegerField(default=0)
    descripcion = models.TextField()
    es_resumen = models.BooleanField(default=False)
    duracion = models.IntegerField(null=True, blank=True)
    inicio = models.DateField(null=True, blank=True)
    fin = models.DateField(null=True, blank=True)
    peso = models.FloatField(null=True, blank=True)
    pct_programa = models.FloatField(null=True, blank=True)
    pct_actual = models.FloatField(null=True, blank=True)
    status = models.CharField(
        max_length=40,
        choices=[
            ("ok", "Ok"),
            ("atraso", "Atraso"),
            ("adelanto", "Adelanto"),
            ("pendiente", "Pendiente"),
        ],
        null=True,
        blank=True,
    )
    razon_accion = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tocal_actividades_programa"
        indexes = [models.Index(fields=["obra"])]

    def __str__(self):
        return str(self.descripcion)


class EstadoPago(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    numero = models.IntegerField()
    periodo = models.TextField(null=True, blank=True)
    monto_uf = models.FloatField()
    numero_factura = models.TextField(null=True, blank=True)
    fecha = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=40,
        choices=[
            ("presentado", "Presentado"),
            ("aprobado", "Aprobado"),
            ("facturado", "Facturado"),
            ("pagado", "Pagado"),
            ("rechazado", "Rechazado"),
        ],
        default="presentado",
    )
    observacion = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tocal_estados_pago"
        unique_together = [("obra", "numero")]

    def __str__(self):
        return str(self.pk)


class Adicional(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    numero = models.IntegerField()
    descripcion = models.TextField()
    fecha_presentacion = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=40,
        choices=[
            ("borrador", "Borrador"),
            ("presentado", "Presentado"),
            ("aprobado", "Aprobado"),
            ("rechazado", "Rechazado"),
        ],
        default="borrador",
    )
    clasificacion = models.TextField(null=True, blank=True)
    monto_uf = models.FloatField(null=True, blank=True)
    monto_aprobado_uf = models.FloatField(null=True, blank=True)
    numero_oc = models.TextField(null=True, blank=True)
    numero_factura = models.TextField(null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tocal_adicionales"
        unique_together = [("obra", "numero")]

    def __str__(self):
        return str(self.descripcion)


class Rdi(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    numero = models.IntegerField()
    medio = models.TextField(null=True, blank=True)
    referencia = models.TextField(null=True, blank=True)
    fecha_envio = models.DateField()
    materia = models.TextField()
    estado = models.CharField(
        max_length=40,
        choices=[
            ("pendiente", "Pendiente"),
            ("respondida", "Respondida"),
            ("incompleta", "Incompleta"),
        ],
        default="pendiente",
    )
    fecha_respuesta = models.DateField(null=True, blank=True)
    especialidad = models.TextField(null=True, blank=True)
    responsable = models.TextField(null=True, blank=True)
    respondida_por = models.TextField(null=True, blank=True)
    observaciones = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tocal_rdi"
        unique_together = [("obra", "numero")]

    def __str__(self):
        return str(self.materia)


class Informe(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    semana = models.ForeignKey(
        "Semana", on_delete=models.CASCADE, related_name="+", db_column="semana_id"
    )
    titulo = models.TextField()
    fecha_corte = models.DateField()
    estado = models.CharField(
        max_length=40,
        choices=[("borrador", "Borrador"), ("emitido", "Emitido")],
        default="borrador",
    )
    comentarios = models.JSONField(blank=True, default=list)
    posibles_problemas = models.JSONField(blank=True, default=list)
    nota_avance = models.TextField(null=True, blank=True)
    autor = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        related_name="+",
        db_column="autor_id",
        null=True,
        blank=True,
    )
    emitido_at = models.DateTimeField(null=True, blank=True)
    pdf_path = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_informes"
        unique_together = [("obra", "semana")]

    def __str__(self):
        return str(self.titulo)


class Foto(Record):
    obra = models.ForeignKey(
        "Obra", on_delete=models.CASCADE, related_name="+", db_column="obra_id"
    )
    storage_path = models.TextField()
    fecha = models.DateField()
    etiqueta = models.CharField(
        max_length=40,
        choices=[
            ("avance", "Avance"),
            ("problema", "Problema"),
            ("seguridad", "Seguridad"),
            ("calidad", "Calidad"),
            ("otra", "Otra"),
        ],
        default="avance",
    )
    sector = models.TextField(null=True, blank=True)
    caption = models.TextField(null=True, blank=True)
    ancho = models.IntegerField(null=True, blank=True)
    alto = models.IntegerField(null=True, blank=True)
    subido_por = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        related_name="+",
        db_column="subido_por",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_obra_fotos"
        indexes = [models.Index(fields=["obra", "fecha"])]

    def __str__(self):
        return str(self.pk)


class InformeFoto(Record):
    informe = models.ForeignKey(
        "Informe", on_delete=models.CASCADE, related_name="+", db_column="informe_id"
    )
    foto = models.ForeignKey(
        "Foto", on_delete=models.CASCADE, related_name="+", db_column="foto_id"
    )
    incluir = models.BooleanField(default=True)
    seccion = models.CharField(
        max_length=40, choices=[("problema", "Problema"), ("obra", "Obra")], null=True, blank=True
    )
    orden = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "tocal_informe_fotos"
        unique_together = [("informe", "foto")]

    def __str__(self):
        return str(self.pk)


class Venta(Record):
    rut_cliente = models.TextField()
    razon_social = models.TextField()
    rubro = models.CharField(
        max_length=40,
        choices=[
            ("energia", "Energia"),
            ("industrial", "Industrial"),
            ("comercial", "Comercial"),
            ("educacional", "Educacional"),
            ("urbanizacion", "Urbanizacion"),
            ("otros", "Otros"),
        ],
        default="otros",
    )
    obra = models.TextField(null=True, blank=True)
    obra_ref = models.ForeignKey(
        "Obra",
        on_delete=models.SET_NULL,
        related_name="+",
        db_column="obra_id",
        null=True,
        blank=True,
    )
    tipo_documento = models.CharField(
        max_length=40,
        choices=[
            ("factura", "Factura"),
            ("factura_electronica", "Factura electronica"),
            ("nota_credito", "Nota credito"),
            ("exenta", "Exenta"),
        ],
        default="factura_electronica",
    )
    numero = models.IntegerField()
    fecha = models.DateField()
    afecto = models.FloatField()
    iva = models.FloatField(default=0)
    total = models.FloatField(default=0)
    uf_dia = models.FloatField()
    afecto_uf = models.FloatField()
    total_uf = models.FloatField()
    observacion = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "tocal_ventas_documentos"
        indexes = [
            models.Index(fields=["tipo_documento", "numero"]),
            models.Index(fields=["fecha"]),
            models.Index(fields=["rut_cliente"]),
        ]

    def __str__(self):
        return str(self.razon_social)


class SolicitudPrivacidad(Record):
    """Solicitudes de derechos de titulares: gestión manual con revisión de identidad.

    No implica que una solicitud sea automática ni que proceda la eliminación.
    """
    TIPO = [
        ("acceso", "Acceso"),
        ("rectificacion", "Rectificación"),
        ("supresion", "Supresión"),
        ("oposicion", "Oposición"),
        ("portabilidad", "Portabilidad"),
        ("bloqueo", "Bloqueo"),
    ]
    ESTADOS = [("pendiente", "Pendiente"), ("revision", "En revisión"),
               ("resuelta", "Resuelta"), ("rechazada", "Rechazada con fundamento")]
    usuario = models.ForeignKey("User", on_delete=models.PROTECT, related_name="solicitudes_privacidad")
    tipo = models.CharField(max_length=20, choices=TIPO)
    detalle = models.TextField(max_length=1000, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="pendiente")
    created_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tocal_solicitudes_privacidad"
        ordering = ["-created_at"]
