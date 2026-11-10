from uuid import uuid4
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('documents', '0001_initial')]
    operations = [
        migrations.CreateModel(
            name='DocumentoTrabajador',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid4, editable=False, serialize=False)),
                ('fecha_emision', models.DateField(null=True, blank=True)),
                ('fecha_vencimiento', models.DateField(null=True, blank=True)),
                ('estado', models.CharField(max_length=16, default='pendiente', choices=[('pendiente','Pendiente'),('aprobado','Aprobado'),('rechazado','Rechazado')])),
                ('observaciones', models.TextField(blank=True)),
                ('revisado_en', models.DateTimeField(null=True, blank=True)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(to='authorization.empresa', on_delete=django.db.models.deletion.PROTECT, related_name='documentos_trabajadores')),
                ('trabajador', models.ForeignKey(to='intranet.trabajador', on_delete=django.db.models.deletion.PROTECT, related_name='documentos')),
                ('tipo_documento', models.ForeignKey(to='documents.tipodocumento', on_delete=django.db.models.deletion.PROTECT, related_name='documentos_trabajadores')),
                ('obra', models.ForeignKey(to='intranet.obra', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name='documentos_trabajadores')),
                ('creado_por', models.ForeignKey(to='intranet.user', on_delete=django.db.models.deletion.PROTECT, related_name='documentos_trabajador_creados')),
                ('revisado_por', models.ForeignKey(to='intranet.user', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name='documentos_trabajador_revisados')),
            ],
            options={'db_table':'tocal_doc_trabajadores', 'ordering':['-creado_en']},
        ),
    ]
