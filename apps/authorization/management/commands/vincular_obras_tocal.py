"""Lista y vincula obras existentes a una empresa RBAC, sin tocar el modelo heredado."""
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.authorization.models import Empresa, EmpresaObra, RegistroAuditoria
from intranet.models import Obra


class Command(BaseCommand):
    help = 'Lista obras existentes y vincula IDs explícitos a una empresa RBAC.'

    def add_arguments(self, parser):
        parser.add_argument('--empresa-id', help='UUID de empresa RBAC existente; requerido para vincular')
        parser.add_argument('--obra-id', action='append', default=[], help='ID de intranet.Obra; repetible')
        parser.add_argument('--listar', action='store_true', help='Listar obras y vínculos actuales sin modificar datos')
        parser.add_argument('--apply', action='store_true', help='Aplicar la vinculación')
        parser.add_argument('--confirmar', help='Escribir VINCULAR para confirmar --apply')

    def handle(self, *args, **options):
        if options['apply'] and options['confirmar'] != 'VINCULAR':
            raise CommandError('Para escribir usa --apply --confirmar VINCULAR.')
        if options['confirmar'] and not options['apply']:
            raise CommandError('--confirmar solo se usa con --apply.')

        empresa = None
        if options['empresa_id']:
            try:
                empresa_id = UUID(options['empresa_id'])
            except (TypeError, ValueError):
                raise CommandError('--empresa-id debe ser UUID válido.')
            empresa = Empresa.objects.filter(pk=empresa_id, activa=True).first()
            if not empresa:
                raise CommandError('La empresa no existe o no está activa.')

        if options['listar'] or not options['obra_id']:
            self.stdout.write('=== OBRAS EXISTENTES (SOLO LECTURA) ===')
            qs = Obra.objects.all().order_by('nombre')
            links = {str(v.obra_id): v.empresa for v in EmpresaObra.objects.select_related('empresa')}
            total = 0
            for obra in qs.iterator():
                vinculo = links.get(str(obra.pk))
                self.stdout.write(
                    f'ID={obra.pk} | nombre={obra.nombre} | razon_social={obra.razon_social} '
                    f'| rut={obra.rut} | activa={obra.activa} '
                    f'| empresa_RBAC={vinculo.nombre if vinculo else "SIN VINCULAR"}'
                )
                total += 1
            self.stdout.write(f'Total: {total} obra(s).')
            if not options['obra_id']:
                if options['apply']:
                    raise CommandError('No indicaste ninguna --obra-id. No se aplicaron cambios.')
                return

        if empresa is None:
            raise CommandError('Para seleccionar obras, indica --empresa-id.')

        ids = options['obra_id']
        if len(ids) != len(set(ids)):
            raise CommandError('Hay IDs duplicados en --obra-id.')
        obras = []
        for id_obra in ids:
            obra = Obra.objects.filter(pk=id_obra).first()
            if obra is None:
                raise CommandError(f'No existe la obra {id_obra}.')
            obras.append(obra)

        actual = {str(x.obra_id): x for x in EmpresaObra.objects.filter(obra_id__in=[o.pk for o in obras]).select_related('empresa')}
        conflictos = [o for o in obras if str(o.pk) in actual and actual[str(o.pk)].empresa_id != empresa.pk]
        if conflictos:
            detalles = ', '.join(f'{o.pk} -> {actual[str(o.pk)].empresa.nombre}' for o in conflictos)
            raise CommandError(f'Obras vinculadas a otra empresa (no se transfieren): {detalles}')

        self.stdout.write('=== VISTA PREVIA DE VINCULACION ===')
        self.stdout.write(f'Empresa destino: {empresa.nombre} ({empresa.pk})')
        pendientes = []
        for obra in obras:
            estado = 'YA VINCULADA (sin cambios)' if str(obra.pk) in actual else 'NUEVA VINCULACION'
            self.stdout.write(f'{estado} | ID={obra.pk} | {obra.nombre} | {obra.razon_social} | RUT={obra.rut}')
            if str(obra.pk) not in actual:
                pendientes.append(obra)
        self.stdout.write('No se modifica Obra, ObraUsuario, User.rol ni el histórico.')
        if not options['apply']:
            self.stdout.write(self.style.WARNING('Solo vista previa. Para aplicar: --apply --confirmar VINCULAR'))
            return

        try:
            with transaction.atomic():
                Empresa.objects.select_for_update().get(pk=empresa.pk, activa=True)
                # La restricción OneToOne de EmpresaObra protege frente a inserciones concurrentes.
                nuevos = []
                for obra in obras:
                    vinculo, creado = EmpresaObra.objects.get_or_create(
                        obra=obra, defaults={'empresa': empresa}
                    )
                    if vinculo.empresa_id != empresa.pk:
                        raise CommandError(f'La obra {obra.pk} fue vinculada a otra empresa concurrentemente.')
                    if creado:
                        nuevos.append(str(obra.pk))
                if nuevos:
                    RegistroAuditoria.objects.create(
                        empresa=empresa,
                        actor=None,
                        accion='obra.vincular_bootstrap',
                        entidad='EmpresaObra',
                        entidad_id=str(empresa.pk),
                        detalle={'obras_vinculadas': nuevos, 'origen': 'management_command'},
                    )
        except Empresa.DoesNotExist:
            raise CommandError('La empresa fue desactivada o eliminada durante la operación.')
        except IntegrityError as exc:
            raise CommandError('Conflicto de concurrencia al vincular obras. Revisa vínculos y reintenta.') from exc

        self.stdout.write(self.style.SUCCESS(
            f'Vinculación aplicada: {len(nuevos)} nueva(s), {len(obras) - len(nuevos)} ya vinculada(s).'
        ))
