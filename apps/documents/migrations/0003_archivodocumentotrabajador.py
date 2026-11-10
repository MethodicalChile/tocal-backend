from uuid import uuid4
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('documents', '0002_documentotrabajador')]

    operations = [
        migrations.CreateModel(
            name='ArchivoDocumentoTrabajador',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid4, editable=False, serialize=False)),
                ('version', models.PositiveIntegerField()),
                ('clave_privada', models.CharField(max_length=500, unique=True)),
                ('nombre_original', models.CharField(max_length=180)),
                ('tipo_mime', models.CharField(max_length=60)),
                ('tamano_bytes', models.PositiveIntegerField()),
                ('sha256', models.CharField(max_length=64)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('documento', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos', to='documents.documentotrabajador')),
                ('subido_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='archivos_documentos_subidos', to='intranet.user')),
            ],
            options={'db_table': 'tocal_doc_archivos_trabajador', 'ordering': ['-version']},
        ),
        migrations.AddConstraint(model_name='archivodocumentotrabajador', constraint=models.UniqueConstraint(fields=('documento', 'version'), name='doc_archivo_version_uniq')),
    ]
