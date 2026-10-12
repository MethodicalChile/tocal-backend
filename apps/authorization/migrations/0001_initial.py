"""Esquema nuevo y no destructivo; no modifica intranet ni sus datos."""
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("intranet", "0003_solicitud_privacidad"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Empresa",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("nombre", models.CharField(max_length=200)),
                ("rut", models.CharField(blank=True, max_length=20, null=True, unique=True)),
                ("activa", models.BooleanField(default=True)),
            ],
            options={"db_table": "tocal_auth_empresas", "ordering": ["nombre"]},
        ),
        migrations.CreateModel(
            name="Permiso",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("codigo", models.CharField(max_length=100, unique=True)),
                ("modulo", models.CharField(max_length=50)),
                ("accion", models.CharField(max_length=50)),
                ("nombre", models.CharField(max_length=160)),
                ("descripcion", models.TextField(blank=True)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={"db_table": "tocal_auth_permisos", "ordering": ["modulo", "accion"]},
        ),
        migrations.CreateModel(
            name="EmpresaObra",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="obras_vinculadas", to="authorization.empresa")),
                ("obra", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="vinculo_empresa", to="intranet.obra")),
            ],
            options={"db_table": "tocal_auth_empresa_obras", "ordering": ["creado_en"]},
        ),
        migrations.CreateModel(
            name="MembresiaEmpresa",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("activa", models.BooleanField(default=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="membresias", to="authorization.empresa")),
                ("usuario", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="membresias_empresas", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "tocal_auth_membresias"},
        ),
        migrations.AddConstraint(
            model_name="membresiaempresa",
            constraint=models.UniqueConstraint(fields=("empresa", "usuario"), name="auth_membresia_empresa_usuario_uniq"),
        ),
        migrations.CreateModel(
            name="Rol",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("codigo", models.SlugField(max_length=64)),
                ("nombre", models.CharField(max_length=120)),
                ("descripcion", models.TextField(blank=True)),
                ("activo", models.BooleanField(default=True)),
                ("protegido", models.BooleanField(default=False)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="roles", to="authorization.empresa")),
            ],
            options={"db_table": "tocal_auth_roles", "ordering": ["empresa", "nombre"]},
        ),
        migrations.AddConstraint(
            model_name="rol",
            constraint=models.UniqueConstraint(fields=("empresa", "codigo"), name="auth_rol_empresa_codigo_uniq"),
        ),
        migrations.CreateModel(
            name="RolPermiso",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("rol", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="permisos_asignados", to="authorization.rol")),
                ("permiso", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="roles_asignados", to="authorization.permiso")),
            ],
            options={"db_table": "tocal_auth_rol_permisos"},
        ),
        migrations.AddConstraint(
            model_name="rolpermiso",
            constraint=models.UniqueConstraint(fields=("rol", "permiso"), name="auth_rol_permiso_uniq"),
        ),
        migrations.CreateModel(
            name="AsignacionRol",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("activa", models.BooleanField(default=True)),
                ("membresia", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones", to="authorization.membresiaempresa")),
                ("rol", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones", to="authorization.rol")),
                ("empresa_obra", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asignaciones_roles", to="authorization.empresaobra")),
            ],
            options={"db_table": "tocal_auth_asignaciones"},
        ),
        migrations.AddConstraint(
            model_name="asignacionrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(empresa_obra__isnull=True),
                fields=("membresia", "rol"),
                name="auth_asig_rol_empresa_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="asignacionrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(empresa_obra__isnull=False),
                fields=("membresia", "rol", "empresa_obra"),
                name="auth_asig_rol_obra_uniq",
            ),
        ),
        migrations.CreateModel(
            name="RegistroAuditoria",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("accion", models.CharField(max_length=120)),
                ("entidad", models.CharField(max_length=120)),
                ("entidad_id", models.CharField(max_length=64)),
                ("detalle", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="auditorias_realizadas", to=settings.AUTH_USER_MODEL)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="auditorias", to="authorization.empresa")),
            ],
            options={"db_table": "tocal_auth_auditoria", "ordering": ["-creado_en"]},
        ),
    ]
