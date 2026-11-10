"""Pruebas sin acceso a Supabase; mock del servicio privado."""
import json
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Trabajador
from apps.authorization.models import Empresa, MembresiaEmpresa, Rol, RolPermiso, Permiso
from apps.authorization.services import assign_role
from apps.documents.models import TipoDocumento, DocumentoTrabajador, ArchivoDocumentoTrabajador


class ArchivosDocumentoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='archivos', password='testpass', name='Archivos')
        self.empresa = Empresa.objects.create(nombre='Empresa archivos')
        MembresiaEmpresa.objects.create(empresa=self.empresa, usuario=self.user)
        rol = Rol.objects.create(empresa=self.empresa, codigo='docs', nombre='Docs')
        for codigo in ('documentos.ver', 'documentos.crear', 'documentos.editar'):
            RolPermiso.objects.create(rol=rol, permiso=Permiso.objects.get(codigo=codigo))
        assign_role(usuario=self.user, empresa=self.empresa, rol=rol)
        self.client.force_login(self.user)
        self.trabajador = Trabajador.objects.create(empresa=self.empresa, nombres='Ana', apellido_paterno='Rojas')
        tipo = TipoDocumento.objects.create(empresa=self.empresa, codigo='contrato', nombre='Contrato', categoria='trabajador')
        self.documento = DocumentoTrabajador.objects.create(empresa=self.empresa, trabajador=self.trabajador, tipo_documento=tipo, creado_por=self.user)
        self.url = reverse('documentos-trabajador-archivos', args=[self.empresa.pk, self.trabajador.pk, self.documento.pk])

    def _upload(self, content=b'%PDF-1.4\ncontenido de prueba'):
        return self.client.post(self.url, {'archivo': SimpleUploadedFile('contrato.pdf', content, content_type='application/pdf')})

    @patch('apps.documents.views.private_storage.write_bytes')
    def test_upload_and_download_private(self, write):
        result = self._upload()
        self.assertEqual(result.status_code, 201, result.content)
        item = ArchivoDocumentoTrabajador.objects.get(pk=result.json()['id'])
        self.assertEqual(item.version, 1)
        self.assertNotIn('clave_privada', result.json())
        self.assertEqual(self.client.get(self.url).json()['results'][0]['version'], 1)
        url = reverse('documentos-trabajador-archivo-descargar', args=[self.empresa.pk, self.trabajador.pk, self.documento.pk, item.pk])
        with patch('apps.documents.views.private_storage.read_bytes', return_value=b'%PDF-1.4\ncontenido de prueba'):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4\ncontenido de prueba')
        self.assertIn('no-store', r['Cache-Control'].lower())

    @patch('apps.documents.views.private_storage.write_bytes')
    def test_two_versions(self, write):
        self.assertEqual(self._upload().status_code, 201)
        self.assertEqual(self._upload().status_code, 201)
        self.assertEqual(list(ArchivoDocumentoTrabajador.objects.filter(documento=self.documento).values_list('version', flat=True)), [2, 1])

    @patch('apps.documents.views.private_storage.write_bytes')
    def test_reject_wrong_extension_and_oversized(self, write):
        r = self.client.post(self.url, {'archivo': SimpleUploadedFile('contrato.exe', b'%PDF-1.4\ncontenido')})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url, {'archivo': SimpleUploadedFile('contrato.pdf', b'not a pdf')})
        self.assertEqual(r.status_code, 400)
        write.assert_not_called()

    @patch('apps.documents.views.private_storage.write_bytes')
    def test_read_only_cannot_upload(self, write):
        RolPermiso.objects.filter(rol__empresa=self.empresa, permiso__codigo='documentos.editar').delete()
        self.assertEqual(self._upload().status_code, 403)
        write.assert_not_called()

    def test_other_company_denied(self):
        other = Empresa.objects.create(nombre='Otra')
        url = reverse('documentos-trabajador-archivos', args=[other.pk, self.trabajador.pk, self.documento.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
