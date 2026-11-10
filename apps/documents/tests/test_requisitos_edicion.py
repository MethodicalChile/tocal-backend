import json
from datetime import date
from django.test import TestCase
from django.urls import reverse
from apps.authorization.models import Empresa, EmpresaObra, MembresiaEmpresa, Rol, RolPermiso, Permiso
from apps.authorization.services import assign_role
from apps.documents.models import TipoDocumento, RequisitoDocumental
from intranet.models import User, Obra


class RequisitosEdicionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='reqeditor', password='testpass', name='Req Editor')
        self.company = Empresa.objects.create(nombre='Empresa A')
        self.other = Empresa.objects.create(nombre='Empresa B')
        MembresiaEmpresa.objects.create(empresa=self.company, usuario=self.user)
        self.role = Rol.objects.create(empresa=self.company, codigo='doc', nombre='Documentos')
        for code in ('documentos.ver', 'documentos.crear', 'documentos.editar'):
            RolPermiso.objects.create(rol=self.role, permiso=Permiso.objects.get(codigo=code))
        assign_role(usuario=self.user, empresa=self.company, rol=self.role)
        self.tipo = TipoDocumento.objects.create(empresa=self.company, codigo='contrato', nombre='Contrato', categoria='trabajador')
        self.regla = RequisitoDocumental.objects.create(empresa=self.company, tipo_documento=self.tipo, obligatorio=True)
        self.client.force_login(self.user)
        self.url = reverse('documentos-requisito-detalle', args=[self.company.id, self.regla.id])

    def patch(self, url, data):
        return self.client.patch(url, data=json.dumps(data), content_type='application/json')

    def test_cambiar_obligatorio_y_desactivar(self):
        response = self.patch(self.url, {'obligatorio': False, 'activo': False})
        self.assertEqual(response.status_code, 200, response.content)
        self.regla.refresh_from_db()
        self.assertFalse(self.regla.obligatorio)
        self.assertFalse(self.regla.activo)

    def test_no_permite_mover_regla_a_otra_empresa(self):
        response = self.patch(self.url, {'empresa_id': str(self.other.id)})
        self.assertEqual(response.status_code, 400)

    def test_no_puede_modificar_regla_de_otra_empresa(self):
        response = self.patch(reverse('documentos-requisito-detalle', args=[self.other.id, self.regla.id]), {'activo': False})
        self.assertEqual(response.status_code, 403)

    def test_sin_permiso_editar(self):
        RolPermiso.objects.filter(rol=self.role, permiso__codigo='documentos.editar').delete()
        self.assertEqual(self.patch(self.url, {'activo': False}).status_code, 403)
