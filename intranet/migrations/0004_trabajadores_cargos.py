from django.db import migrations, models
import django.db.models.deletion
import intranet.models


class Migration(migrations.Migration):
    dependencies = [
        ("intranet", "0003_solicitud_privacidad"),
        ("authorization", "0002_catalogo_permisos"),
    ]

    operations = [
        migrations.CreateModel(
            name="Cargo",
            fields=[
                ("id", models.CharField(default=intranet.models.new_id, editable=False, max_length=64, primary_key=True, serialize=False)),
                ("codigo", models.SlugField(max_length=64)),
                ("nombre", models.CharField(max_length=150)),
                ("descripcion", models.TextField(blank=True)),
                ("activo", models.BooleanField(default=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cargos", to="authorization.empresa")),
            ],
            options={"db_table": "tocal_cargos", "ordering": ["nombre"]},
        ),
        migrations.CreateModel(
            name="Trabajador",
            fields=[
                ("id", models.CharField(default=intranet.models.new_id, editable=False, max_length=64, primary_key=True, serialize=False)),
                ("nombres", models.CharField(max_length=150)),
                ("apellido_paterno", models.CharField(max_length=100)),
                ("apellido_materno", models.CharField(blank=True, max_length=100)),
                ("rut", models.CharField(blank=True, max_length=20, null=True)),
                ("activo", models.BooleanField(default=True)),
                ("creado_en", models.DateTimeField(default=intranet.models.timezone.now)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="trabajadores", to="authorization.empresa")),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="fichas_trabajador", to="intranet.user")),
            ],
            options={"db_table": "tocal_trabajadores", "ordering": ["apellido_paterno", "nombres"]},
        ),
        migrations.CreateModel(
            name="AsignacionTrabajadorObra",
            fields=[
                ("id", models.CharField(default=intranet.models.new_id, editable=False, max_length=64, primary_key=True, serialize=False)),
                ("fecha_inicio", models.DateField()),
                ("fecha_fin", models.DateField(blank=True, null=True)),
                ("observaciones", models.TextField(blank=True)),
                ("creado_en", models.DateTimeField(default=intranet.models.timezone.now)),
                ("cargo", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones_trabajadores", to="intranet.cargo")),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones_trabajadores", to="authorization.empresa")),
                ("obra", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones_trabajadores", to="intranet.obra")),
                ("trabajador", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones_obras", to="intranet.trabajador")),
            ],
            options={"db_table": "tocal_trabajador_obras", "ordering": ["-fecha_inicio"]},
        ),
        migrations.AddConstraint(model_name="cargo", constraint=models.UniqueConstraint(fields=("empresa", "codigo"), name="tocal_cargo_empresa_codigo_uniq")),
        migrations.AddConstraint(model_name="trabajador", constraint=models.UniqueConstraint(condition=models.Q(rut__isnull=False) & ~models.Q(rut=""), fields=("empresa", "rut"), name="tocal_trabajador_empresa_rut_uniq")),
        migrations.AddConstraint(model_name="trabajador", constraint=models.UniqueConstraint(condition=models.Q(usuario__isnull=False), fields=("empresa", "usuario"), name="tocal_trabajador_empresa_usuario_uniq")),
        migrations.AddConstraint(model_name="asignaciontrabajadorobra", constraint=models.UniqueConstraint(condition=models.Q(fecha_fin__isnull=True), fields=("trabajador", "obra"), name="tocal_asignacion_abierta_uniq")),
        migrations.AddConstraint(model_name="asignaciontrabajadorobra", constraint=models.CheckConstraint(condition=models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=models.F("fecha_inicio")), name="tocal_asignacion_fechas_validas")),
    ]
