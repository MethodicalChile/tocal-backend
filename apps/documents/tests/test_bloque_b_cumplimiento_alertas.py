import json
from datetime import date, timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Trabajador, Obra, Cargo, AsignacionTrabajadorObra
from apps.authorization.models import Empresa, EmpresaObra, MembresiaEmpresa, Rol, RolPermiso, Permiso, RegistroAuditoria
from apps.authorization.services import assign_role
from apps.documents.models import (
    TipoDocumento,
    RequisitoDocumental,
    DocumentoTrabajador,
    ArchivoDocumentoTrabajador,
    RevisionDocumentoTrabajador,
    AlertaVencimiento,
)


class BloqueBCumplimientoAlertasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='admin_b',
            email='admin_b@tocal.cl',
            password='testpass',
            name='Admin Bloque B',
        )
        self.company = Empresa.objects.create(nombre='Constructora Tocal B')
        MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.user)
        role = Rol.objects.create(empresa=self.company, codigo='admin_doc', nombre='Admin Documental')
        for code in (
            'documentos.ver',
            'documentos.crear',
            'documentos.editar',
            'documentos.aprobar',
            'alertas.ver',
            'alertas.configurar',
        ):
            RolPermiso.objects.create(rol=role, permiso=Permiso.objects.get(codigo=code))
        assign_role(usuario=self.user, empresa=self.company, rol=role)
        self.client.force_login(self.user)

        self.cargo = Cargo.objects.create(empresa=self.company, nombre='Maestro Primera')
        self.obra = Obra.objects.create(
            nombre='Obra Norte',
            razon_social='Mandante Norte',
            rut='76.111.222-3',
            servicio='Edificación',
            inicio_contrato=date(2026, 1, 1),
        )
        EmpresaObra.objects.create(empresa=self.company, obra=self.obra)
        self.worker = Trabajador.objects.create(
            empresa=self.company,
            nombres='Carlos',
            apellido_paterno='Soto',
        )
        AsignacionTrabajadorObra.objects.create(
            empresa=self.company,
            trabajador=self.worker,
            obra=self.obra,
            cargo=self.cargo,
            fecha_inicio=date(2026, 1, 1),
        )
        self.tipo_contrato = TipoDocumento.objects.create(
            empresa=self.company,
            codigo='contrato',
            nombre='Contrato de Trabajo',
            categoria='trabajador',
            requiere_vencimiento=False,
        )
        self.tipo_examen = TipoDocumento.objects.create(
            empresa=self.company,
            codigo='examen_altura',
            nombre='Examen Altura Física',
            categoria='trabajador',
            requiere_vencimiento=True,
        )
        self.tipo_induccion = TipoDocumento.objects.create(
            empresa=self.company,
            codigo='induccion_obra',
            nombre='Inducción Obra Norte',
            categoria='trabajador',
            requiere_vencimiento=True,
        )

    def test_etapa4_aprobacion_versionada_rechazo_con_motivo_y_reenvio(self):
        doc_url = reverse('documentos-trabajador', args=[self.company.pk, self.worker.pk])
        resp = self.client.post(
            doc_url,
            data=json.dumps({'tipo_documento_id': str(self.tipo_contrato.pk)}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        doc_id = resp.json()['id']
        rev_url = reverse('documentos-trabajador-revision', args=[self.company.pk, self.worker.pk, doc_id])
        arch_url = reverse('documentos-trabajador-archivos', args=[self.company.pk, self.worker.pk, doc_id])

        # T4.1: No permitir aprobar sin archivo adjunto
        r_no_file = self.client.patch(
            rev_url,
            data=json.dumps({'estado': 'aprobado'}),
            content_type='application/json',
        )
        self.assertEqual(r_no_file.status_code, 400)
        self.assertIn('evidencia', r_no_file.json()['error'].lower())

        # Subir versión 1
        pdf_v1 = SimpleUploadedFile('contrato_v1.pdf', b'%PDF-1.4 version 1 content', content_type='application/pdf')
        r_up1 = self.client.post(arch_url, {'archivo': pdf_v1})
        self.assertEqual(r_up1.status_code, 201)
        v1_id = r_up1.json()['id']

        # T4.4: Rechazar sin motivo debe fallar con 400
        r_rej_bad = self.client.patch(
            rev_url,
            data=json.dumps({'estado': 'rechazado'}),
            content_type='application/json',
        )
        self.assertEqual(r_rej_bad.status_code, 400)

        # T4.4: Rechazar con motivo obligatorio
        r_rej_ok = self.client.patch(
            rev_url,
            data=json.dumps({'estado': 'rechazado', 'motivo_rechazo': 'Falta firma del trabajador'}),
            content_type='application/json',
        )
        self.assertEqual(r_rej_ok.status_code, 200)
        self.assertEqual(r_rej_ok.json()['motivo_rechazo'], 'Falta firma del trabajador')

        # T4.2: Aprobar versión 1
        r_app = self.client.patch(
            rev_url,
            data=json.dumps({'estado': 'aprobado', 'observaciones': 'Firma verificada'}),
            content_type='application/json',
        )
        self.assertEqual(r_app.status_code, 200)
        self.assertEqual(r_app.json()['version_aprobada_id'], v1_id)
        self.assertEqual(r_app.json()['version_aprobada_numero'], 1)

        # T4.3: Subir versión 2 invalida aprobación anterior y vuelve a pendiente
        pdf_v2 = SimpleUploadedFile('contrato_v2.pdf', b'%PDF-1.4 version 2 updated', content_type='application/pdf')
        r_up2 = self.client.post(arch_url, {'archivo': pdf_v2})
        self.assertEqual(r_up2.status_code, 201)
        doc = DocumentoTrabajador.objects.get(pk=doc_id)
        self.assertEqual(doc.estado, 'pendiente')
        self.assertIsNone(doc.version_aprobada)

        # Historial de revisiones disponible en GET archivos
        r_hist = self.client.get(arch_url)
        self.assertEqual(r_hist.status_code, 200)
        self.assertEqual(len(r_hist.json()['results']), 2)
        self.assertEqual(len(r_hist.json()['revisiones']), 2)
        self.assertEqual(RevisionDocumentoTrabajador.objects.filter(documento=doc).count(), 2)

    def test_t4_6_comando_normalizar_documentos_aprobados(self):
        doc = DocumentoTrabajador.objects.create(
            empresa=self.company,
            trabajador=self.worker,
            tipo_documento=self.tipo_contrato,
            estado='aprobado',
            creado_por=self.user,
        )
        call_command('normalizar_documentos_aprobados')
        doc.refresh_from_db()
        self.assertEqual(doc.estado, 'pendiente')

    def test_etapa3_prevencion_requisitos_duplicados(self):
        req_url = reverse('documentos-requisitos', args=[self.company.pk])
        r1 = self.client.post(
            req_url,
            data=json.dumps({
                'tipo_documento_id': str(self.tipo_contrato.pk),
                'cargo_id': str(self.cargo.pk),
                'obligatorio': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(
            req_url,
            data=json.dumps({
                'tipo_documento_id': str(self.tipo_contrato.pk),
                'cargo_id': str(self.cargo.pk),
                'obligatorio': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 400)

    def test_etapa5_cumplimiento_documental_automatico(self):
        # Requisito por cargo (contrato) + requisito general (examen) + requisito por obra (inducción)
        RequisitoDocumental.objects.create(
            empresa=self.company,
            tipo_documento=self.tipo_contrato,
            cargo=self.cargo,
            obligatorio=True,
        )
        RequisitoDocumental.objects.create(
            empresa=self.company,
            tipo_documento=self.tipo_examen,
            obligatorio=True,
        )
        RequisitoDocumental.objects.create(
            empresa=self.company,
            tipo_documento=self.tipo_induccion,
            obra=self.obra,
            obligatorio=True,
        )

        # Contrato aprobado con archivo
        doc_contrato = DocumentoTrabajador.objects.create(
            empresa=self.company,
            trabajador=self.worker,
            tipo_documento=self.tipo_contrato,
            estado='aprobado',
            creado_por=self.user,
        )
        arch = ArchivoDocumentoTrabajador.objects.create(
            documento=doc_contrato,
            version=1,
            clave_privada='dummy/c.pdf',
            nombre_original='c.pdf',
            tipo_mime='application/pdf',
            tamano_bytes=100,
            sha256='a' * 64,
            subido_por=self.user,
        )
        doc_contrato.version_aprobada = arch
        doc_contrato.save()

        # Examen vencido
        DocumentoTrabajador.objects.create(
            empresa=self.company,
            trabajador=self.worker,
            tipo_documento=self.tipo_examen,
            fecha_vencimiento=date.today() - timedelta(days=5),
            estado='aprobado',
            creado_por=self.user,
        )

        cump_url = reverse('documentos-trabajador-cumplimiento', args=[self.company.pk, self.worker.pk])
        r = self.client.get(cump_url)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['total_obligatorios'], 3)
        self.assertEqual(data['aprobados'], 1)
        self.assertEqual(data['vencidos'], 1)
        self.assertEqual(data['faltantes'], 1)
        self.assertFalse(data['habilitado_documentalmente'])
        self.assertEqual(len(data['por_obra']), 1)

    def test_etapa6_alertas_vencimiento_y_comando_idempotente(self):
        cfg_url = reverse('documentos-alertas-configuracion', args=[self.company.pk])
        r_cfg = self.client.patch(
            cfg_url,
            data=json.dumps({
                'dias_anticipacion': [30, 15, 7],
                'notificar_vencidos': True,
                'activo': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(r_cfg.status_code, 200)

        doc_por_vencer = DocumentoTrabajador.objects.create(
            empresa=self.company,
            trabajador=self.worker,
            tipo_documento=self.tipo_examen,
            fecha_vencimiento=date.today() + timedelta(days=5),
            estado='aprobado',
            creado_por=self.user,
        )
        # Ejecutar comando 2 veces para comprobar idempotencia (T6.4)
        call_command('detectar_vencimientos', empresa_id=str(self.company.pk))
        call_command('detectar_vencimientos', empresa_id=str(self.company.pk))

        alertas = AlertaVencimiento.objects.filter(empresa=self.company, documento_id=str(doc_por_vencer.pk))
        self.assertEqual(alertas.count(), 1)
        alerta = alertas.first()
        self.assertEqual(alerta.umbral_dias, 7)

        # Consultar y marcar como leída con auditoría (T6.3, T6.5)
        list_url = reverse('documentos-alertas', args=[self.company.pk])
        r_list = self.client.get(list_url)
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(r_list.json()['resumen']['no_leidas'], 1)

        det_url = reverse('documentos-alerta-detalle', args=[self.company.pk, alerta.pk])
        r_mark = self.client.patch(det_url, data=json.dumps({'leida': True}), content_type='application/json')
        self.assertEqual(r_mark.status_code, 200)
        self.assertTrue(r_mark.json()['leida'])
        self.assertTrue(
            RegistroAuditoria.objects.filter(empresa=self.company, accion='alertas.vencimiento.marcar_leida').exists()
        )
