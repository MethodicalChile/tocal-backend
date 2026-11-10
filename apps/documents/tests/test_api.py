import json
from datetime import date
from django.test import TestCase
from django.urls import reverse
from intranet.models import User, Cargo, Obra
from apps.authorization.models import Empresa, EmpresaObra, MembresiaEmpresa, Rol, RolPermiso, Permiso
from apps.authorization.services import assign_role
from apps.documents.models import TipoDocumento


class DocumentsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='docuser', password='testpass', name='Doc User')
        self.company = Empresa.objects.create(nombre='A')
        self.other = Empresa.objects.create(nombre='B')
        MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.user)
        role = Rol.objects.create(empresa=self.company, codigo='doc', nombre='Documental')
        for code in ('documentos.ver', 'documentos.crear'):
            RolPermiso.objects.create(rol=role, permiso=Permiso.objects.get(codigo=code))
        assign_role(usuario=self.user, empresa=self.company, rol=role)
        self.client.force_login(self.user)
        self.tipos_url = reverse('documentos-tipos', args=[self.company.pk])
        self.req_url = reverse('documentos-requisitos', args=[self.company.pk])

    def post(self, url, data):
        return self.client.post(url, data=json.dumps(data), content_type='application/json')

    def test_create_and_list_type(self):
        r = self.post(self.tipos_url, {'codigo': 'irl', 'nombre': 'IRL', 'categoria': 'trabajador'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(self.client.get(self.tipos_url).json()['results']), 1)

    def test_reject_other_company(self):
        url = reverse('documentos-tipos', args=[self.other.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post(url, {'codigo': 'x', 'nombre': 'X', 'categoria': 'empresa'}).status_code, 403)

    def test_reject_other_company_type_and_cargo(self):
        foreign = TipoDocumento.objects.create(empresa=self.other, codigo='x', nombre='X', categoria='trabajador')
        self.assertEqual(self.post(self.req_url, {'tipo_documento_id': str(foreign.pk)}).status_code, 400)
        own = TipoDocumento.objects.create(empresa=self.company, codigo='y', nombre='Y', categoria='trabajador')
        cargo = Cargo.objects.create(empresa=self.other, codigo='maestro', nombre='Maestro')
        self.assertEqual(self.post(self.req_url, {'tipo_documento_id': str(own.pk), 'cargo_id': cargo.pk}).status_code, 400)

    def test_reject_unlinked_work(self):
        own = TipoDocumento.objects.create(empresa=self.company, codigo='z', nombre='Z', categoria='empresa')
        obra = Obra.objects.create(nombre='Obra', razon_social='E', rut='R', servicio='Construcción', inicio_contrato=date(2026, 1, 1))
        EmpresaObra.objects.create(empresa=self.other, obra=obra)
        self.assertEqual(self.post(self.req_url, {'tipo_documento_id': str(own.pk), 'obra_id': obra.pk}).status_code, 400)

    def test_read_only_permission_blocks_write(self):
        RolPermiso.objects.filter(rol__empresa=self.company, permiso__codigo='documentos.crear').delete()
        self.assertEqual(self.post(self.tipos_url, {'codigo': 'x', 'nombre': 'X', 'categoria': 'empresa'}).status_code, 403)
