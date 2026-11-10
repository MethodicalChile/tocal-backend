"""Catálogo documental multiempresa. No almacena archivos ni datos clínicos."""
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import models


class TipoDocumento(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='tipos_documento')
    codigo = models.SlugField(max_length=64)
    nombre = models.CharField(max_length=180)
    categoria = models.CharField(max_length=20, choices=[('empresa', 'Empresa'), ('trabajador', 'Trabajador'), ('equipo', 'Equipo')])
    descripcion = models.TextField(blank=True)
    requiere_vencimiento = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_tipos'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='tocal_doc_tipo_empresa_codigo_uniq')]

    def __str__(self):
        return self.nombre


class RequisitoDocumental(models.Model):
    """Regla para empresa, cargo o una obra. La obra es opcional, no inferir herencia."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='requisitos_documentales')
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name='requisitos')
    cargo = models.ForeignKey('intranet.Cargo', on_delete=models.PROTECT, null=True, blank=True, related_name='requisitos_documentales')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='requisitos_documentales')
    obligatorio = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_requisitos'
        ordering = ['creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.tipo_documento_id and self.tipo_documento.empresa_id != self.empresa_id:
            errores['tipo_documento'] = 'El tipo documental pertenece a otra empresa.'
        if self.empresa_id and self.cargo_id and self.cargo.empresa_id != self.empresa_id:
            errores['cargo'] = 'El cargo pertenece a otra empresa.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
        if self.tipo_documento_id and self.cargo_id and self.tipo_documento.categoria != 'trabajador':
            errores['cargo'] = 'Solo se pueden asociar cargos a requisitos de trabajador.'
        if self.activo and self.empresa_id and self.tipo_documento_id:
            dup_qs = RequisitoDocumental.objects.filter(
                empresa_id=self.empresa_id,
                tipo_documento_id=self.tipo_documento_id,
                cargo_id=self.cargo_id,
                obra_id=self.obra_id,
                activo=True,
            )
            if self.pk:
                dup_qs = dup_qs.exclude(pk=self.pk)
            if dup_qs.exists():
                errores['tipo_documento'] = 'Ya existe un requisito activo para este tipo documental, cargo y obra.'
        if errores:
            raise ValidationError(errores)


class DocumentoTrabajador(models.Model):
    """Expediente de metadatos; no almacena archivos ni enlaces públicos."""
    ESTADOS = [('pendiente', 'Pendiente'), ('aprobado', 'Aprobado'), ('rechazado', 'Rechazado')]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='documentos_trabajadores')
    trabajador = models.ForeignKey('intranet.Trabajador', on_delete=models.PROTECT, related_name='documentos')
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name='documentos_trabajadores')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_trabajadores')
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=16, choices=ESTADOS, default='pendiente')
    observaciones = models.TextField(blank=True)
    motivo_rechazo = models.TextField(blank=True)
    version_aprobada = models.ForeignKey(
        'ArchivoDocumentoTrabajador',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    creado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='documentos_trabajador_creados')
    revisado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_trabajador_revisados')
    revisado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_trabajadores'
        ordering = ['-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.trabajador_id and self.trabajador.empresa_id != self.empresa_id:
            errores['trabajador'] = 'El trabajador pertenece a otra empresa.'
        if self.empresa_id and self.tipo_documento_id:
            if self.tipo_documento.empresa_id != self.empresa_id or self.tipo_documento.categoria != 'trabajador' or not self.tipo_documento.activo:
                errores['tipo_documento'] = 'Tipo documental no válido para este trabajador.'
            elif self.tipo_documento.requiere_vencimiento and not self.fecha_vencimiento:
                errores['fecha_vencimiento'] = 'Este tipo requiere vencimiento.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
            elif self.trabajador_id:
                from intranet.models import AsignacionTrabajadorObra
                if not AsignacionTrabajadorObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id, trabajador_id=self.trabajador_id).exists():
                    errores['obra'] = 'El trabajador no está asignado a la obra.'
        if self.fecha_emision and self.fecha_vencimiento and self.fecha_vencimiento < self.fecha_emision:
            errores['fecha_vencimiento'] = 'El vencimiento debe ser posterior a la emisión.'
        if errores:
            raise ValidationError(errores)


class ArchivoDocumentoTrabajador(models.Model):
    """Una versión inmutable del archivo privado de un documento."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoTrabajador, on_delete=models.PROTECT, related_name='archivos')
    version = models.PositiveIntegerField()
    clave_privada = models.CharField(max_length=500, unique=True)
    nombre_original = models.CharField(max_length=180)
    tipo_mime = models.CharField(max_length=60)
    tamano_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    subido_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='archivos_documentos_subidos')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_archivos_trabajador'
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['documento', 'version'], name='doc_archivo_version_uniq')]


class RevisionDocumentoTrabajador(models.Model):
    """Historial inmutable de revisiones (aprobación/rechazo) asociadas a una versión del archivo."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoTrabajador, on_delete=models.PROTECT, related_name='revisiones')
    archivo = models.ForeignKey(
        ArchivoDocumentoTrabajador,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='revisiones',
    )
    estado = models.CharField(max_length=16, choices=DocumentoTrabajador.ESTADOS)
    observaciones = models.TextField(blank=True)
    revisado_por = models.ForeignKey(
        'intranet.User',
        on_delete=models.PROTECT,
        related_name='revisiones_documentos_trabajador',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_revisiones_trabajador'
        ordering = ['-creado_en']


def _default_dias_anticipacion():
    return [60, 30, 15, 7]


def _default_roles_destinatarios():
    return ['administrador_general', 'prevencionista', 'jefe_obra']


class ConfiguracionAlertaEmpresa(models.Model):
    """Parámetros de alertas de vencimiento documental por empresa."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.OneToOneField(
        'authorization.Empresa',
        on_delete=models.CASCADE,
        related_name='configuracion_alertas',
    )
    dias_anticipacion = models.JSONField(default=_default_dias_anticipacion)
    notificar_vencidos = models.BooleanField(default=True)
    roles_destinatarios = models.JSONField(default=_default_roles_destinatarios)
    activo = models.BooleanField(default=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tocal_doc_config_alertas'


class AlertaVencimiento(models.Model):
    """Alerta generada por documento vencido o próximo a vencer (sin duplicados por umbral)."""
    ENTIDADES = [
        ('trabajador', 'Trabajador'),
        ('empresa', 'Empresa'),
        ('equipo', 'Equipo'),
    ]
    NIVELES = [
        ('por_vencer', 'Por vencer'),
        ('vencido', 'Vencido'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey(
        'authorization.Empresa',
        on_delete=models.CASCADE,
        related_name='alertas_vencimiento',
    )
    obra = models.ForeignKey(
        'intranet.Obra',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alertas_vencimiento',
    )
    entidad_tipo = models.CharField(max_length=20, choices=ENTIDADES)
    entidad_id = models.CharField(max_length=64)
    documento_id = models.CharField(max_length=64)
    titulo = models.CharField(max_length=240)
    nivel = models.CharField(max_length=20, choices=NIVELES)
    umbral_dias = models.IntegerField(default=0)
    fecha_vencimiento = models.DateField()
    dias_restantes = models.IntegerField()
    leida = models.BooleanField(default=False)
    leida_por = models.ForeignKey(
        'intranet.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    leida_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tocal_doc_alertas_vencimiento'
        ordering = ['dias_restantes', '-creada_en']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'empresa',
                    'entidad_tipo',
                    'documento_id',
                    'nivel',
                    'umbral_dias',
                    'fecha_vencimiento',
                ],
                name='tocal_doc_alerta_venc_uniq',
            )
        ]


class DocumentoEmpresa(models.Model):
    """Documento corporativo o asociado a una obra específica de la empresa."""
    ESTADOS = DocumentoTrabajador.ESTADOS
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='documentos_empresa')
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name='documentos_empresa')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_empresa')
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=16, choices=ESTADOS, default='pendiente')
    observaciones = models.TextField(blank=True)
    motivo_rechazo = models.TextField(blank=True)
    version_aprobada = models.ForeignKey(
        'ArchivoDocumentoEmpresa',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    creado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='documentos_empresa_creados')
    revisado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_empresa_revisados')
    revisado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_empresas'
        ordering = ['-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.tipo_documento_id:
            if (
                self.tipo_documento.empresa_id != self.empresa_id
                or self.tipo_documento.categoria != 'empresa'
                or not self.tipo_documento.activo
            ):
                errores['tipo_documento'] = 'Tipo documental no válido para documento de empresa.'
            elif self.tipo_documento.requiere_vencimiento and not self.fecha_vencimiento:
                errores['fecha_vencimiento'] = 'Este tipo documental requiere fecha de vencimiento.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
        if self.fecha_emision and self.fecha_vencimiento and self.fecha_vencimiento < self.fecha_emision:
            errores['fecha_vencimiento'] = 'El vencimiento debe ser posterior a la emisión.'
        if errores:
            raise ValidationError(errores)


class ArchivoDocumentoEmpresa(models.Model):
    """Versión inmutable del archivo privado de un documento empresarial."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoEmpresa, on_delete=models.PROTECT, related_name='archivos')
    version = models.PositiveIntegerField()
    clave_privada = models.CharField(max_length=500, unique=True)
    nombre_original = models.CharField(max_length=180)
    tipo_mime = models.CharField(max_length=60)
    tamano_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    subido_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='archivos_empresa_subidos')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_archivos_empresa'
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['documento', 'version'], name='doc_emp_archivo_version_uniq')]


class RevisionDocumentoEmpresa(models.Model):
    """Historial inmutable de revisiones para un documento empresarial."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoEmpresa, on_delete=models.PROTECT, related_name='revisiones')
    archivo = models.ForeignKey(
        ArchivoDocumentoEmpresa,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='revisiones',
    )
    estado = models.CharField(max_length=16, choices=DocumentoEmpresa.ESTADOS)
    observaciones = models.TextField(blank=True)
    revisado_por = models.ForeignKey(
        'intranet.User',
        on_delete=models.PROTECT,
        related_name='revisiones_documentos_empresa',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_revisiones_empresa'
        ordering = ['-creado_en']


class Equipo(models.Model):
    """Catálogo empresarial de equipos, vehículos y maquinaria."""
    ESTADOS = [
        ('operativo', 'Operativo'),
        ('mantencion', 'En mantención'),
        ('fuera_servicio', 'Fuera de servicio'),
        ('baja', 'De baja'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='equipos')
    codigo = models.SlugField(max_length=64)
    nombre = models.CharField(max_length=180)
    tipo_equipo = models.CharField(max_length=80, default='Maquinaria')
    marca = models.CharField(max_length=100, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    patente_o_serie = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=32, choices=ESTADOS, default='operativo')
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_equipos'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='tocal_equipo_empresa_codigo_uniq')]

    def __str__(self):
        return f'{self.nombre} ({self.codigo})'


class AsignacionEquipoObra(models.Model):
    """Historial de asignaciones de un equipo a obras de la empresa."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='asignaciones_equipos')
    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name='asignaciones')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, related_name='asignaciones_equipos')
    responsable = models.CharField(max_length=160, blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    observaciones = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_equipos_asignaciones_obra'
        ordering = ['-fecha_inicio', '-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.equipo_id and self.equipo.empresa_id != self.empresa_id:
            errores['equipo'] = 'El equipo pertenece a otra empresa.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            errores['fecha_fin'] = 'La fecha de término no puede ser anterior a la fecha de inicio.'
        if errores:
            raise ValidationError(errores)


class DocumentoEquipo(models.Model):
    """Documento técnico o normativo asociado a un equipo/maquinaria."""
    ESTADOS = DocumentoTrabajador.ESTADOS
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='documentos_equipos')
    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name='documentos')
    tipo_documento = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name='documentos_equipos')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_equipos')
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=16, choices=ESTADOS, default='pendiente')
    observaciones = models.TextField(blank=True)
    motivo_rechazo = models.TextField(blank=True)
    version_aprobada = models.ForeignKey(
        'ArchivoDocumentoEquipo',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    creado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='documentos_equipo_creados')
    revisado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, null=True, blank=True, related_name='documentos_equipo_revisados')
    revisado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_equipos'
        ordering = ['-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.equipo_id and self.equipo.empresa_id != self.empresa_id:
            errores['equipo'] = 'El equipo pertenece a otra empresa.'
        if self.empresa_id and self.tipo_documento_id:
            if (
                self.tipo_documento.empresa_id != self.empresa_id
                or self.tipo_documento.categoria != 'equipo'
                or not self.tipo_documento.activo
            ):
                errores['tipo_documento'] = 'Tipo documental no válido para equipo.'
            elif self.tipo_documento.requiere_vencimiento and not self.fecha_vencimiento:
                errores['fecha_vencimiento'] = 'Este tipo documental requiere fecha de vencimiento.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
        if self.fecha_emision and self.fecha_vencimiento and self.fecha_vencimiento < self.fecha_emision:
            errores['fecha_vencimiento'] = 'El vencimiento debe ser posterior a la emisión.'
        if errores:
            raise ValidationError(errores)


class ArchivoDocumentoEquipo(models.Model):
    """Versión inmutable del archivo privado de un documento de equipo."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoEquipo, on_delete=models.PROTECT, related_name='archivos')
    version = models.PositiveIntegerField()
    clave_privada = models.CharField(max_length=500, unique=True)
    nombre_original = models.CharField(max_length=180)
    tipo_mime = models.CharField(max_length=60)
    tamano_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    subido_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='archivos_equipo_subidos')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_archivos_equipo'
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['documento', 'version'], name='doc_eq_archivo_version_uniq')]


class RevisionDocumentoEquipo(models.Model):
    """Historial inmutable de revisiones para un documento de equipo."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    documento = models.ForeignKey(DocumentoEquipo, on_delete=models.PROTECT, related_name='revisiones')
    archivo = models.ForeignKey(
        ArchivoDocumentoEquipo,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='revisiones',
    )
    estado = models.CharField(max_length=16, choices=DocumentoEquipo.ESTADOS)
    observaciones = models.TextField(blank=True)
    revisado_por = models.ForeignKey(
        'intranet.User',
        on_delete=models.PROTECT,
        related_name='revisiones_documentos_equipo',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_doc_revisiones_equipo'
        ordering = ['-creado_en']


class TipoCapacitacion(models.Model):
    """Catálogo empresarial de cursos, charlas e inducciones preventivas."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='tipos_capacitacion')
    codigo = models.SlugField(max_length=64)
    nombre = models.CharField(max_length=180)
    descripcion = models.TextField(blank=True)
    horas_sugeridas = models.PositiveIntegerField(default=1)
    requiere_vencimiento = models.BooleanField(default=True)
    vigencia_meses = models.PositiveIntegerField(default=12)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_prev_tipos_capacitacion'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='tocal_cap_tipo_empresa_codigo_uniq')]


class RequisitoCapacitacion(models.Model):
    """Regla de capacitación exigible por cargo y/o obra."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='requisitos_capacitacion')
    tipo_capacitacion = models.ForeignKey(TipoCapacitacion, on_delete=models.PROTECT, related_name='requisitos')
    cargo = models.ForeignKey('intranet.Cargo', on_delete=models.PROTECT, null=True, blank=True, related_name='requisitos_capacitacion')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='requisitos_capacitacion')
    obligatorio = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_prev_requisitos_capacitacion'
        ordering = ['creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.tipo_capacitacion_id and self.tipo_capacitacion.empresa_id != self.empresa_id:
            errores['tipo_capacitacion'] = 'El tipo de capacitación pertenece a otra empresa.'
        if self.empresa_id and self.cargo_id and self.cargo.empresa_id != self.empresa_id:
            errores['cargo'] = 'El cargo pertenece a otra empresa.'
        if self.empresa_id and self.obra_id:
            from apps.authorization.models import EmpresaObra
            if not EmpresaObra.objects.filter(empresa_id=self.empresa_id, obra_id=self.obra_id).exists():
                errores['obra'] = 'La obra no pertenece a la empresa.'
        if errores:
            raise ValidationError(errores)


class CapacitacionTrabajador(models.Model):
    """Registro de capacitación o charla realizada por un trabajador."""
    ESTADOS = [
        ('vigente', 'Vigente'),
        ('vencida', 'Vencida'),
        ('observada', 'Con observaciones'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='capacitaciones_trabajadores')
    trabajador = models.ForeignKey('intranet.Trabajador', on_delete=models.PROTECT, related_name='capacitaciones')
    tipo_capacitacion = models.ForeignKey(TipoCapacitacion, on_delete=models.PROTECT, related_name='registros')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='capacitaciones_trabajadores')
    fecha_realizacion = models.DateField()
    fecha_vencimiento = models.DateField(null=True, blank=True)
    horas = models.PositiveIntegerField(default=1)
    relator = models.CharField(max_length=160, blank=True)
    estado = models.CharField(max_length=16, choices=ESTADOS, default='vigente')
    clave_evidencia = models.CharField(max_length=500, blank=True)
    nombre_evidencia = models.CharField(max_length=180, blank=True)
    observaciones = models.TextField(blank=True)
    registrado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='capacitaciones_registradas')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_prev_capacitaciones_trabajador'
        ordering = ['-fecha_realizacion', '-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.trabajador_id and self.trabajador.empresa_id != self.empresa_id:
            errores['trabajador'] = 'El trabajador pertenece a otra empresa.'
        if self.empresa_id and self.tipo_capacitacion_id and self.tipo_capacitacion.empresa_id != self.empresa_id:
            errores['tipo_capacitacion'] = 'El tipo de capacitación pertenece a otra empresa.'
        if self.fecha_realizacion and self.fecha_vencimiento and self.fecha_vencimiento < self.fecha_realizacion:
            errores['fecha_vencimiento'] = 'La fecha de vencimiento no puede ser anterior a la realización.'
        if errores:
            raise ValidationError(errores)


class CategoriaEPP(models.Model):
    """Catálogo empresarial de Elementos de Protección Personal (EPP)."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='categorias_epp')
    codigo = models.SlugField(max_length=64)
    nombre = models.CharField(max_length=180)
    descripcion = models.TextField(blank=True)
    vida_util_meses = models.PositiveIntegerField(default=6)
    requiere_vencimiento = models.BooleanField(default=False)
    obligatorio_terreno = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_prev_categorias_epp'
        ordering = ['nombre']
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='tocal_epp_cat_empresa_codigo_uniq')]


class EntregaEPP(models.Model):
    """Registro histórico de entrega, recambio o devolución de EPP a un trabajador."""
    ESTADOS = [
        ('entregado', 'Entregado'),
        ('renovado', 'Renovado'),
        ('devuelto', 'Devuelto'),
        ('extraviado', 'Extraviado / Dañado'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey('authorization.Empresa', on_delete=models.PROTECT, related_name='entregas_epp')
    trabajador = models.ForeignKey('intranet.Trabajador', on_delete=models.PROTECT, related_name='entregas_epp')
    categoria_epp = models.ForeignKey(CategoriaEPP, on_delete=models.PROTECT, related_name='entregas')
    obra = models.ForeignKey('intranet.Obra', on_delete=models.PROTECT, null=True, blank=True, related_name='entregas_epp')
    elemento = models.CharField(max_length=180)
    talla_o_serie = models.CharField(max_length=80, blank=True)
    cantidad = models.PositiveIntegerField(default=1)
    fecha_entrega = models.DateField()
    fecha_vencimiento = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='entregado')
    firmado_recepcion = models.BooleanField(default=True)
    clave_comprobante = models.CharField(max_length=500, blank=True)
    nombre_comprobante = models.CharField(max_length=180, blank=True)
    observaciones = models.TextField(blank=True)
    entregado_por = models.ForeignKey('intranet.User', on_delete=models.PROTECT, related_name='entregas_epp_realizadas')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tocal_prev_entregas_epp'
        ordering = ['-fecha_entrega', '-creado_en']

    def clean(self):
        super().clean()
        errores = {}
        if self.empresa_id and self.trabajador_id and self.trabajador.empresa_id != self.empresa_id:
            errores['trabajador'] = 'El trabajador pertenece a otra empresa.'
        if self.empresa_id and self.categoria_epp_id and self.categoria_epp.empresa_id != self.empresa_id:
            errores['categoria_epp'] = 'La categoría de EPP pertenece a otra empresa.'
        if self.fecha_entrega and self.fecha_vencimiento and self.fecha_vencimiento < self.fecha_entrega:
            errores['fecha_vencimiento'] = 'La fecha de vencimiento no puede ser anterior a la entrega.'
        if errores:
            raise ValidationError(errores)

