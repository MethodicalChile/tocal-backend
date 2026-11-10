from uuid import uuid4
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('authorization', '0003_permisos_informes_edicion'), ('intranet', '0004_trabajadores_cargos')]
    operations = [
        migrations.CreateModel(name='TipoDocumento', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid4, editable=False, serialize=False)),
            ('codigo', models.SlugField(max_length=64)), ('nombre', models.CharField(max_length=180)),
            ('categoria', models.CharField(max_length=20, choices=[('empresa', 'Empresa'), ('trabajador', 'Trabajador'), ('equipo', 'Equipo')])),
            ('descripcion', models.TextField(blank=True)), ('requiere_vencimiento', models.BooleanField(default=False)),
            ('activo', models.BooleanField(default=True)), ('creado_en', models.DateTimeField(auto_now_add=True)),
            ('empresa', models.ForeignKey(to='authorization.empresa', on_delete=django.db.models.deletion.PROTECT, related_name='tipos_documento')),
        ], options={'db_table': 'tocal_doc_tipos', 'ordering': ['nombre']}),
        migrations.AddConstraint(model_name='tipodocumento', constraint=models.UniqueConstraint(fields=['empresa', 'codigo'], name='tocal_doc_tipo_empresa_codigo_uniq')),
        migrations.CreateModel(name='RequisitoDocumental', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid4, editable=False, serialize=False)),
            ('obligatorio', models.BooleanField(default=True)), ('activo', models.BooleanField(default=True)),
            ('creado_en', models.DateTimeField(auto_now_add=True)),
            ('empresa', models.ForeignKey(to='authorization.empresa', on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_documentales')),
            ('tipo_documento', models.ForeignKey(to='documents.tipodocumento', on_delete=django.db.models.deletion.PROTECT, related_name='requisitos')),
            ('cargo', models.ForeignKey(to='intranet.cargo', on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_documentales', null=True, blank=True)),
            ('obra', models.ForeignKey(to='intranet.obra', on_delete=django.db.models.deletion.PROTECT, related_name='requisitos_documentales', null=True, blank=True)),
        ], options={'db_table': 'tocal_doc_requisitos', 'ordering': ['creado_en']}),
    ]
