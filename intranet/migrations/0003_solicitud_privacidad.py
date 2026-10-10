from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import intranet.models

class Migration(migrations.Migration):
    dependencies = [('intranet', '0002_alter_foto_subido_por_alter_informe_autor')]
    operations = [
        migrations.CreateModel(
            name='SolicitudPrivacidad',
            fields=[
                ('id', models.CharField(default=intranet.models.new_id, editable=False, max_length=64, primary_key=True, serialize=False)),
                ('tipo', models.CharField(choices=[('acceso','Acceso'),('rectificacion','Rectificación'),('supresion','Supresión'),('oposicion','Oposición'),('portabilidad','Portabilidad'),('bloqueo','Bloqueo')], max_length=20)),
                ('detalle', models.TextField(blank=True, max_length=1000)),
                ('estado', models.CharField(choices=[('pendiente','Pendiente'),('revision','En revisión'),('resuelta','Resuelta'),('rechazada','Rechazada con fundamento')], default='pendiente', max_length=20)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='solicitudes_privacidad', to='intranet.user')),
            ],
            options={'db_table': 'tocal_solicitudes_privacidad', 'ordering':['-created_at']},
        ),
    ]
