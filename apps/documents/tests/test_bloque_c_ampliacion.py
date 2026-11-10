import json
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.authorization.models import (
    Empresa,
    EmpresaObra,
    MembresiaEmpresa,
    Permiso,
    Rol,
    RolPermiso,
)
from apps.authorization.services import assign_role
from apps.documents.models import (
    RequisitoDocumental,
    TipoDocumento,
)
from intranet.models import AsignacionTrabajadorObra, Cargo, Obra, Trabajador

User = get_user_model()


class BloqueCAmpliacionTests(TestCase):
    """Pruebas integrales para Bloque C (Etapas 2, 7, 8, 9 y 10)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='admin_c',
            email='admin_c@tocal.cl',
            password='PasswordSeguro123!',
            name='Admin Bloque C',
        )
        self.empresa = Empresa.objects.create(nombre='Constructora Bloque C', activa=True)
        self.empresa_ajena = Empresa.objects.create(nombre='Otra Constructora', activa=True)

        hoy = timezone.localdate()
        self.obra_1 = Obra.objects.create(
            nombre='Obra Central',
            razon_social='Constructora Bloque C SpA',
            rut='76.100.200-3',
            servicio='Edificación',
            inicio_contrato=hoy,
            activa=True,
        )
        self.obra_2 = Obra.objects.create(
            nombre='Obra Norte',
            razon_social='Constructora Bloque C SpA',
            rut='76.100.200-3',
            servicio='Montaje',
            inicio_contrato=hoy,
            activa=True,
        )
        EmpresaObra.objects.create(empresa=self.empresa, obra=self.obra_1)
        EmpresaObra.objects.create(empresa=self.empresa, obra=self.obra_2)

        codigos_permisos = [
            'empresas.ver', 'empresas.editar',
            'obras.ver', 'obras.crear', 'obras.editar',
            'empleados.ver', 'empleados.crear', 'empleados.editar', 'empleados.ver_sensibles',
            'cargos.ver', 'cargos.crear', 'cargos.editar',
            'asignaciones.ver', 'asignaciones.crear', 'asignaciones.editar',
            'tipos_documentales.ver', 'tipos_documentales.crear', 'tipos_documentales.editar',
            'requisitos_documentales.ver', 'requisitos_documentales.crear', 'requisitos_documentales.editar',
            'documentos.ver', 'documentos.crear', 'documentos.editar', 'documentos.aprobar',
            'documentos.subir', 'documentos.descargar',
            'equipos.ver', 'equipos.crear', 'equipos.editar',
            'alertas.ver', 'alertas.configurar',
            'informes.ver', 'informes.exportar',
        ]
        MembresiaEmpresa.objects.create(empresa=self.empresa, usuario=self.user)
        self.rol = Rol.objects.create(empresa=self.empresa, codigo='admin_integral', nombre='Admin Integral', activo=True)
        for cod in codigos_permisos:
            perm, _ = Permiso.objects.get_or_create(
                codigo=cod,
                defaults={'modulo': cod.split('.')[0], 'accion': cod.split('.')[1], 'descripcion': cod},
            )
            RolPermiso.objects.get_or_create(rol=self.rol, permiso=perm)

        assign_role(usuario=self.user, empresa=self.empresa, rol=self.rol)
        self.client.force_login(self.user)

    def test_etapa2_semilla_catalogo_cargos_tocal_y_cambio_cargo_historico(self):
        # Sembrar catálogo de cargos levantados en Tocal
        res = self.client.post(f'/api/empresas/{self.empresa.id}/cargos/catalogo-tocal')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertGreaterEqual(body['creados'], 12)

        cargo_maestro = Cargo.objects.filter(empresa=self.empresa, codigo='maestro-primera').first()
        cargo_jefe = Cargo.objects.filter(empresa=self.empresa, codigo='jefe-obras').first()
        self.assertIsNotNone(cargo_maestro)
        self.assertIsNotNone(cargo_jefe)

        trabajador = Trabajador.objects.create(
            empresa=self.empresa,
            rut='15.222.333-4',
            nombres='Pedro',
            apellido_paterno='Soto',
            activo=True,
        )
        hoy = timezone.localdate()
        asig = AsignacionTrabajadorObra.objects.create(
            empresa=self.empresa,
            obra=self.obra_1,
            trabajador=trabajador,
            cargo=cargo_maestro,
            fecha_inicio=hoy - timedelta(days=30),
        )

        # Cambiar de cargo sobre asignación vigente debe cerrar la anterior y abrir una nueva
        res_patch = self.client.patch(
            f'/api/empresas/{self.empresa.id}/obras/{self.obra_1.id}/trabajadores/asignaciones/{asig.id}',
            data=json.dumps({
                'cargo_id': cargo_jefe.id,
                'fecha_cambio': hoy.isoformat(),
            }),
            content_type='application/json',
        )
        self.assertEqual(res_patch.status_code, 200)
        self.assertEqual(AsignacionTrabajadorObra.objects.filter(trabajador=trabajador).count(), 2)

    def test_etapa7_documentos_empresa_aprobacion_segura_y_cumplimiento(self):
        tipo_emp = TipoDocumento.objects.create(
            empresa=self.empresa,
            codigo='reglamento-interno',
            nombre='Reglamento Interno Higiene y Seguridad',
            categoria='empresa',
            requiere_vencimiento=True,
            activo=True,
        )
        RequisitoDocumental.objects.create(
            empresa=self.empresa,
            tipo_documento=tipo_emp,
            obligatorio=True,
            activo=True,
        )

        # Cumplimiento inicial debe reflejar faltante
        comp_1 = self.client.get(f'/api/documentos/empresas/{self.empresa.id}/cumplimiento-empresa/').json()
        self.assertEqual(comp_1['estado_global'], 'incumplimiento')
        self.assertEqual(comp_1['resumen']['faltantes'], 1)

        # Crear documento de empresa
        futuro = (timezone.localdate() + timedelta(days=90)).isoformat()
        res_doc = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/documentos-empresa/',
            data=json.dumps({
                'tipo_documento_id': str(tipo_emp.id),
                'fecha_vencimiento': futuro,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_doc.status_code, 201)
        doc_id = res_doc.json()['id']

        # Intentar aprobar sin evidencia debe fallar con 400
        res_apr_fail = self.client.patch(
            f'/api/documentos/empresas/{self.empresa.id}/documentos-empresa/{doc_id}/revision/',
            data=json.dumps({'estado': 'aprobado'}),
            content_type='application/json',
        )
        self.assertEqual(res_apr_fail.status_code, 400)

        # Subir archivo PDF válido
        pdf_file = SimpleUploadedFile('reglamento.pdf', b'%PDF-1.4 contenido reglamento', content_type='application/pdf')
        res_up = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/documentos-empresa/{doc_id}/archivos/',
            data={'archivo': pdf_file},
        )
        self.assertEqual(res_up.status_code, 201)

        # Ahora sí aprobar
        res_apr_ok = self.client.patch(
            f'/api/documentos/empresas/{self.empresa.id}/documentos-empresa/{doc_id}/revision/',
            data=json.dumps({'estado': 'aprobado', 'observaciones': 'Reglamento validado'}),
            content_type='application/json',
        )
        self.assertEqual(res_apr_ok.status_code, 200)

        comp_2 = self.client.get(f'/api/documentos/empresas/{self.empresa.id}/cumplimiento-empresa/').json()
        self.assertEqual(comp_2['estado_global'], 'al_dia')
        self.assertEqual(comp_2['porcentaje_cumplimiento'], 100)

    def test_etapa8_equipos_asignaciones_documentos_y_cumplimiento(self):
        tipo_eq = TipoDocumento.objects.create(
            empresa=self.empresa,
            codigo='revision-tecnica',
            nombre='Revisión Técnica al Día',
            categoria='equipo',
            requiere_vencimiento=True,
            activo=True,
        )
        RequisitoDocumental.objects.create(
            empresa=self.empresa,
            tipo_documento=tipo_eq,
            obligatorio=True,
            activo=True,
        )

        # Crear equipo
        res_eq = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/equipos/',
            data=json.dumps({
                'codigo': 'exc-cat-01',
                'nombre': 'Retroexcavadora CAT 416',
                'tipo_equipo': 'Maquinaria pesada',
                'patente_o_serie': 'ABCD-12',
            }),
            content_type='application/json',
        )
        self.assertEqual(res_eq.status_code, 201)
        equipo_id = res_eq.json()['id']

        # Asignar equipo a obra
        hoy = timezone.localdate().isoformat()
        res_asig = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/equipos/{equipo_id}/asignaciones/',
            data=json.dumps({
                'obra_id': self.obra_1.id,
                'responsable': 'Operador Juan',
                'fecha_inicio': hoy,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_asig.status_code, 201)

        # Crear documento de equipo, subir evidencia y aprobar
        futuro = (timezone.localdate() + timedelta(days=60)).isoformat()
        res_doc = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/equipos/{equipo_id}/documentos/',
            data=json.dumps({
                'tipo_documento_id': str(tipo_eq.id),
                'fecha_vencimiento': futuro,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_doc.status_code, 201)
        doc_id = res_doc.json()['id']

        pdf_file = SimpleUploadedFile('rev_tecnica.pdf', b'%PDF-1.4 revision tecnica', content_type='application/pdf')
        self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/equipos/{equipo_id}/documentos/{doc_id}/archivos/',
            data={'archivo': pdf_file},
        )
        self.client.patch(
            f'/api/documentos/empresas/{self.empresa.id}/equipos/{equipo_id}/documentos/{doc_id}/revision/',
            data=json.dumps({'estado': 'aprobado'}),
            content_type='application/json',
        )

        comp = self.client.get(f'/api/documentos/empresas/{self.empresa.id}/equipos/{equipo_id}/cumplimiento/').json()
        self.assertEqual(comp['estado_global'], 'al_dia')
        self.assertEqual(comp['porcentaje_cumplimiento'], 100)

    def test_etapa9_y_10_capacitaciones_epp_habilitacion_dashboard_y_csv(self):
        cargo = Cargo.objects.create(empresa=self.empresa, codigo='soldador', nombre='Soldador', activo=True)
        trabajador = Trabajador.objects.create(
            empresa=self.empresa,
            rut='16.444.555-6',
            nombres='Carlos',
            apellido_paterno='Muñoz',
            activo=True,
        )
        hoy = timezone.localdate()
        AsignacionTrabajadorObra.objects.create(
            empresa=self.empresa,
            obra=self.obra_1,
            trabajador=trabajador,
            cargo=cargo,
            fecha_inicio=hoy - timedelta(days=10),
        )

        # Crear tipo de capacitación y requisito para el cargo
        res_tc = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/capacitaciones/tipos/',
            data=json.dumps({
                'codigo': 'trabajo-caliente',
                'nombre': 'Curso Trabajo en Caliente',
                'vigencia_meses': 12,
                'horas_duracion': 4,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_tc.status_code, 201)
        tc_id = res_tc.json()['id']

        res_rc = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/capacitaciones/requisitos/',
            data=json.dumps({
                'tipo_capacitacion_id': tc_id,
                'cargo_id': str(cargo.id),
                'obligatorio': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_rc.status_code, 201)

        # Antes de registrar la capacitación, la habilitación preventiva debe ser no_habilitado
        hab_1 = self.client.get(
            f'/api/documentos/empresas/{self.empresa.id}/trabajadores/{trabajador.id}/habilitacion-preventiva/'
        ).json()
        self.assertEqual(hab_1['estado_habilitacion'], 'no_habilitado')

        # Registrar capacitación al trabajador
        res_cap = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/trabajadores/{trabajador.id}/capacitaciones/',
            data=json.dumps({
                'tipo_capacitacion_id': tc_id,
                'obra_id': self.obra_1.id,
                'fecha_realizacion': hoy.isoformat(),
                'relator': 'Mutual',
            }),
            content_type='application/json',
        )
        self.assertEqual(res_cap.status_code, 201)

        # Crear categoría EPP y registrar entrega
        res_cat = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/epp/categorias/',
            data=json.dumps({
                'codigo': 'mascara-soldar',
                'nombre': 'Máscara de soldar fotosensible',
                'vida_util_dias': 180,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_cat.status_code, 201)
        cat_id = res_cat.json()['id']

        res_epp = self.client.post(
            f'/api/documentos/empresas/{self.empresa.id}/trabajadores/{trabajador.id}/epp/',
            data=json.dumps({
                'categoria_id': cat_id,
                'fecha_entrega': hoy.isoformat(),
                'cantidad': 1,
                'firmado_recepcion': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(res_epp.status_code, 201)

        # Ahora la habilitación preventiva debe estar habilitada
        hab_2 = self.client.get(
            f'/api/documentos/empresas/{self.empresa.id}/trabajadores/{trabajador.id}/habilitacion-preventiva/'
        ).json()
        self.assertEqual(hab_2['estado_habilitacion'], 'habilitado')

        # Dashboard de cumplimiento y exportación CSV
        res_dash = self.client.get(f'/api/documentos/empresas/{self.empresa.id}/dashboard-cumplimiento/')
        self.assertEqual(res_dash.status_code, 200)
        dash = res_dash.json()
        self.assertIn('trabajadores', dash)
        self.assertIn('obras', dash)

        res_csv = self.client.get(f'/api/documentos/empresas/{self.empresa.id}/exportar-cumplimiento/')
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv; charset=utf-8')

