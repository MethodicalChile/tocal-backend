import json
from datetime import date
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Trabajador, Obra
from apps.authorization.models import Empresa, EmpresaObra, MembresiaEmpresa, Rol, RolPermiso, Permiso
from apps.authorization.services import assign_role
from apps.documents.models import TipoDocumento, DocumentoTrabajador, ArchivoDocumentoTrabajador


class ExpedienteTrabajadorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='expuser', password='testpass', name='Exp User')
        self.company = Empresa.objects.create(nombre='Empresa expediente')
        self.other = Empresa.objects.create(nombre='Otra empresa')
        MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.user)
        role = Rol.objects.create(empresa=self.company, codigo='expediente', nombre='Expediente')
        for code in ('documentos.ver', 'documentos.crear', 'documentos.editar'):
            RolPermiso.objects.create(rol=role, permiso=Permiso.objects.get(codigo=code))
        assign_role(usuario=self.user, empresa=self.company, rol=role)
        self.client.force_login(self.user)
        self.worker = Trabajador.objects.create(empresa=self.company, nombres='Ana', apellido_paterno='Rojas')
        self.foreign = Trabajador.objects.create(empresa=self.other, nombres='B', apellido_paterno='Perez')
        self.type = TipoDocumento.objects.create(empresa=self.company, codigo='irl', nombre='IRL', categoria='trabajador', requiere_vencimiento=True)
        self.url = reverse('documentos-trabajador', args=[self.company.pk, self.worker.pk])

    def post(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type='application/json')

    def test_registrar_listar_y_revisar(self):
        response = self.post(self.url, {'tipo_documento_id': str(self.type.pk), 'fecha_emision': '2026-01-01', 'fecha_vencimiento': '2027-01-01'})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['estado'], 'pendiente')
        self.assertEqual(len(self.client.get(self.url).json()['results']), 1)
        doc_id = response.json()['id']
        revision = reverse('documentos-trabajador-revision', args=[self.company.pk, self.worker.pk, doc_id])
        # T4.1: Sin archivo adjunto no se puede aprobar
        r_no_file = self.client.patch(revision, data=json.dumps({'estado': 'aprobado'}), content_type='application/json')
        self.assertEqual(r_no_file.status_code, 400, r_no_file.content)
        # Adjuntar evidencia activa y aprobar
        ArchivoDocumentoTrabajador.objects.create(
            documento_id=doc_id,
            version=1,
            clave_privada=f'dummy/{doc_id}/evidencia.pdf',
            nombre_original='evidencia.pdf',
            tipo_mime='application/pdf',
            tamano_bytes=120,
            sha256='0' * 64,
            subido_por=self.user,
        )
        r = self.client.patch(revision, data=json.dumps({'estado': 'aprobado'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(DocumentoTrabajador.objects.get(pk=doc_id).estado, 'aprobado')

    def test_requiere_vencimiento(self):
        r = self.post(self.url, {'tipo_documento_id': str(self.type.pk)})
        self.assertEqual(r.status_code, 400)

    def test_no_consultar_trabajador_ajeno(self):
        url = reverse('documentos-trabajador', args=[self.company.pk, self.foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post(url, {'tipo_documento_id': str(self.type.pk)}).status_code, 404)

    def test_no_permitir_tipo_ajeno(self):
        foreign_type = TipoDocumento.objects.create(empresa=self.other, codigo='c', nombre='C', categoria='trabajador')
        self.assertEqual(self.post(self.url, {'tipo_documento_id':str(foreign_type.pk)}).status_code, 400)

    def test_no_permitir_obra_ajena(self):
        work = Obra.objects.create(nombre='Obra B', razon_social='B', rut='R', servicio='Servicio', inicio_contrato=date(2026,1,1))
        EmpresaObra.objects.create(empresa=self.other, obra=work)
        r = self.post(self.url, {'tipo_documento_id':str(self.type.pk), 'fecha_vencimiento':'2027-01-01', 'obra_id':work.pk})
        self.assertEqual(r.status_code, 400)

    def test_lectura_no_permite_crear(self):
        RolPermiso.objects.filter(rol__empresa=self.company, permiso__codigo='documentos.crear').delete()
        self.assertEqual(self.post(self.url, {'tipo_documento_id':str(self.type.pk), 'fecha_vencimiento':'2027-01-01'}).status_code, 403)
