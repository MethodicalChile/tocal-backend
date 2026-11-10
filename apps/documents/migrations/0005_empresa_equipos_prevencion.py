# Generated for Etapas 7, 8 y 9 (Documentos de empresa, Equipos/Maquinaria, Capacitaciones y EPP)

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authorization', '0004_permisos_complementarios'),
        ('documents', '0004_aprobacion_cumplimiento_alertas'),
        ('intranet', '0004_trabajadores_cargos'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ArchivoDocumentoEmpresa',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.PositiveIntegerField()),
                ('clave_privada', models.CharField(max_length=500, unique=True)),
                ('nombre_original', models.CharField(max_length=180)),
                ('tipo_mime', models.CharField(max_length=60)),
                ('tamano_bytes', models.PositiveIntegerField()),
                ('sha256', models.CharField(max_length=64)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('subido_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos_empresa_subidos', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'tocal_doc_archivos_empresa',
                'ordering': ['-version'],
            },
        ),
        migrations.CreateModel(
            name='DocumentoEmpresa',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('fecha_emision', models.DateField(blank=True, null=True)),
                ('fecha_vencimiento', models.DateField(blank=True, null=True)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente'), ('aprobado', 'Aprobado'), ('rechazado', 'Rechazado')], default='pendiente', max_length=16)),
                ('observaciones', models.TextField(blank=True)),
                ('motivo_rechazo', models.TextField(blank=True)),
                ('revisado_en', models.DateTimeField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('creado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_empresa_creados', to=settings.AUTH_USER_MODEL)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_empresa', to='authorization.empresa')),
                ('obra', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_empresa', to='intranet.obra')),
                ('revisado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_empresa_revisados', to=settings.AUTH_USER_MODEL)),
                ('tipo_documento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_empresa', to='documents.tipodocumento')),
                ('version_aprobada', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='documents.archivodocumentoempresa')),
            ],
            options={
                'db_table': 'tocal_doc_empresas',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.AddField(
            model_name='archivodocumentoempresa',
            name='documento',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos', to='documents.documentoempresa'),
        ),
        migrations.AddConstraint(
            model_name='archivodocumentoempresa',
            constraint=models.UniqueConstraint(fields=('documento', 'version'), name='doc_emp_archivo_version_uniq'),
        ),
        migrations.CreateModel(
            name='RevisionDocumentoEmpresa',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente'), ('aprobado', 'Aprobado'), ('rechazado', 'Rechazado')], max_length=16)),
                ('observaciones', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('archivo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='revisiones', to='documents.archivodocumentoempresa')),
                ('documento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='revisiones', to='documents.documentoempresa')),
                ('revisado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='revisiones_documentos_empresa', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'tocal_doc_revisiones_empresa',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='Equipo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('codigo', models.SlugField(max_length=64)),
                ('nombre', models.CharField(max_length=180)),
                ('tipo_equipo', models.CharField(default='Maquinaria', max_length=80)),
                ('marca', models.CharField(blank=True, max_length=100)),
                ('modelo', models.CharField(blank=True, max_length=100)),
                ('patente_o_serie', models.CharField(blank=True, max_length=100)),
                ('estado', models.CharField(choices=[('operativo', 'Operativo'), ('mantencion', 'En mantención'), ('fuera_servicio', 'Fuera de servicio'), ('baja', 'De baja')], default='operativo', max_length=32)),
                ('activo', models.BooleanField(default=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='equipos', to='authorization.empresa')),
            ],
            options={
                'db_table': 'tocal_equipos',
                'ordering': ['nombre'],
                'constraints': [models.UniqueConstraint(fields=('empresa', 'codigo'), name='tocal_equipo_empresa_codigo_uniq')],
            },
        ),
        migrations.CreateModel(
            name='AsignacionEquipoObra',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('responsable', models.CharField(blank=True, max_length=160)),
                ('fecha_inicio', models.DateField()),
                ('fecha_fin', models.DateField(blank=True, null=True)),
                ('observaciones', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='asignaciones_equipos', to='authorization.empresa')),
                ('equipo', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='asignaciones', to='documents.equipo')),
                ('obra', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='asignaciones_equipos', to='intranet.obra')),
            ],
            options={
                'db_table': 'tocal_equipos_asignaciones_obra',
                'ordering': ['-fecha_inicio', '-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='ArchivoDocumentoEquipo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.PositiveIntegerField()),
                ('clave_privada', models.CharField(max_length=500, unique=True)),
                ('nombre_original', models.CharField(max_length=180)),
                ('tipo_mime', models.CharField(max_length=60)),
                ('tamano_bytes', models.PositiveIntegerField()),
                ('sha256', models.CharField(max_length=64)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('subido_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos_equipo_subidos', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'tocal_doc_archivos_equipo',
                'ordering': ['-version'],
            },
        ),
        migrations.CreateModel(
            name='DocumentoEquipo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('fecha_emision', models.DateField(blank=True, null=True)),
                ('fecha_vencimiento', models.DateField(blank=True, null=True)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente'), ('aprobado', 'Aprobado'), ('rechazado', 'Rechazado')], default='pendiente', max_length=16)),
                ('observaciones', models.TextField(blank=True)),
                ('motivo_rechazo', models.TextField(blank=True)),
                ('revisado_en', models.DateTimeField(blank=True, null=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('creado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_equipo_creados', to=settings.AUTH_USER_MODEL)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_equipos', to='authorization.empresa')),
                ('equipo', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos', to='documents.equipo')),
                ('obra', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_equipos', to='intranet.obra')),
                ('revisado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_equipo_revisados', to=settings.AUTH_USER_MODEL)),
                ('tipo_documento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_equipos', to='documents.tipodocumento')),
                ('version_aprobada', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='documents.archivodocumentoequipo')),
            ],
            options={
                'db_table': 'tocal_doc_equipos',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.AddField(
            model_name='archivodocumentoequipo',
            name='documento',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos', to='documents.documentoequipo'),
        ),
        migrations.AddConstraint(
            model_name='archivodocumentoequipo',
            constraint=models.UniqueConstraint(fields=('documento', 'version'), name='doc_eq_archivo_version_uniq'),
        ),
        migrations.CreateModel(
            name='RevisionDocumentoEquipo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente'), ('aprobado', 'Aprobado'), ('rechazado', 'Rechazado')], max_length=16)),
                ('observaciones', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('archivo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='revisiones', to='documents.archivodocumentoequipo')),
                ('documento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='revisiones', to='documents.documentoequipo')),
                ('revisado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='revisiones_documentos_equipo', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'tocal_doc_revisiones_equipo',
                'ordering': ['-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='TipoCapacitacion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('codigo', models.SlugField(max_length=64)),
                ('nombre', models.CharField(max_length=180)),
                ('descripcion', models.TextField(blank=True)),
                ('horas_sugeridas', models.PositiveIntegerField(default=1)),
                ('requiere_vencimiento', models.BooleanField(default=True)),
                ('vigencia_meses', models.PositiveIntegerField(default=12)),
                ('activo', models.BooleanField(default=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tipos_capacitacion', to='authorization.empresa')),
            ],
            options={
                'db_table': 'tocal_prev_tipos_capacitacion',
                'ordering': ['nombre'],
                'constraints': [models.UniqueConstraint(fields=('empresa', 'codigo'), name='tocal_cap_tipo_empresa_codigo_uniq')],
            },
        ),
        migrations.CreateModel(
            name='RequisitoCapacitacion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('obligatorio', models.BooleanField(default=True)),
                ('activo', models.BooleanField(default=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('cargo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_capacitacion', to='intranet.cargo')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_capacitacion', to='authorization.empresa')),
                ('obra', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_capacitacion', to='intranet.obra')),
                ('tipo_capacitacion', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='requisitos', to='documents.tipocapacitacion')),
            ],
            options={
                'db_table': 'tocal_prev_requisitos_capacitacion',
                'ordering': ['creado_en'],
            },
        ),
        migrations.CreateModel(
            name='CapacitacionTrabajador',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('fecha_realizacion', models.DateField()),
                ('fecha_vencimiento', models.DateField(blank=True, null=True)),
                ('horas', models.PositiveIntegerField(default=1)),
                ('relator', models.CharField(blank=True, max_length=160)),
                ('estado', models.CharField(choices=[('vigente', 'Vigente'), ('vencida', 'Vencida'), ('observada', 'Con observaciones')], default='vigente', max_length=16)),
                ('clave_evidencia', models.CharField(blank=True, max_length=500)),
                ('nombre_evidencia', models.CharField(blank=True, max_length=180)),
                ('observaciones', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='capacitaciones_trabajadores', to='authorization.empresa')),
                ('obra', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='capacitaciones_trabajadores', to='intranet.obra')),
                ('registrado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='capacitaciones_registradas', to=settings.AUTH_USER_MODEL)),
                ('tipo_capacitacion', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='registros', to='documents.tipocapacitacion')),
                ('trabajador', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='capacitaciones', to='intranet.trabajador')),
            ],
            options={
                'db_table': 'tocal_prev_capacitaciones_trabajador',
                'ordering': ['-fecha_realizacion', '-creado_en'],
            },
        ),
        migrations.CreateModel(
            name='CategoriaEPP',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('codigo', models.SlugField(max_length=64)),
                ('nombre', models.CharField(max_length=180)),
                ('descripcion', models.TextField(blank=True)),
                ('vida_util_meses', models.PositiveIntegerField(default=6)),
                ('requiere_vencimiento', models.BooleanField(default=False)),
                ('obligatorio_terreno', models.BooleanField(default=True)),
                ('activo', models.BooleanField(default=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='categorias_epp', to='authorization.empresa')),
            ],
            options={
                'db_table': 'tocal_prev_categorias_epp',
                'ordering': ['nombre'],
                'constraints': [models.UniqueConstraint(fields=('empresa', 'codigo'), name='tocal_epp_cat_empresa_codigo_uniq')],
            },
        ),
        migrations.CreateModel(
            name='EntregaEPP',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('elemento', models.CharField(max_length=180)),
                ('talla_o_serie', models.CharField(blank=True, max_length=80)),
                ('cantidad', models.PositiveIntegerField(default=1)),
                ('fecha_entrega', models.DateField()),
                ('fecha_vencimiento', models.DateField(blank=True, null=True)),
                ('estado', models.CharField(choices=[('entregado', 'Entregado'), ('renovado', 'Renovado'), ('devuelto', 'Devuelto'), ('extraviado', 'Extraviado / Dañado')], default='entregado', max_length=20)),
                ('firmado_recepcion', models.BooleanField(default=True)),
                ('clave_comprobante', models.CharField(blank=True, max_length=500)),
                ('nombre_comprobante', models.CharField(blank=True, max_length=180)),
                ('observaciones', models.TextField(blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('categoria_epp', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='entregas', to='documents.categoriaepp')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='entregas_epp', to='authorization.empresa')),
                ('entregado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='entregas_epp_realizadas', to=settings.AUTH_USER_MODEL)),
                ('obra', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='entregas_epp', to='intranet.obra')),
                ('trabajador', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='entregas_epp', to='intranet.trabajador')),
            ],
            options={
                'db_table': 'tocal_prev_entregas_epp',
                'ordering': ['-fecha_entrega', '-creado_en'],
            },
        ),
    ]

