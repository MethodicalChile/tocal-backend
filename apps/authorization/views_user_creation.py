"""Alta de nuevos usuarios, sin modificar vistas de asignaciones existentes."""
import uuid
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from .models import Empresa, MembresiaEmpresa
from .views_assignments import route, payload, can_admin, audit

@route(['POST'])
def member_create(request, empresa_id):
    """Alta de usuario nuevo + membresía, con opción de rol inicial y ficha de trabajador vinculada."""
    data = payload(request)
    allowed_fields = {'nombre', 'email', 'password', 'rol_id', 'obra_id', 'crear_trabajador', 'rut'}
    if not {'nombre', 'email', 'password'}.issubset(set(data)) or not set(data).issubset(allowed_fields):
        raise ValueError('Se requieren nombre, email y password')
    nombre = str(data['nombre']).strip()
    email = str(data['email']).strip().lower()
    password = data['password']
    rol_id = str(data.get('rol_id') or '').strip() or None
    obra_id = str(data.get('obra_id') or '').strip() or None
    crear_trabajador = bool(data.get('crear_trabajador'))
    rut_trabajador = str(data.get('rut') or '').strip() or None
    if not nombre or len(nombre) > 200:
        raise ValueError('Nombre inválido')
    User = get_user_model()
    email = User.objects.normalize_email(email).lower()
    validate_email(email)
    if len(email) > 254 or not isinstance(password, str):
        raise ValueError('Correo o contraseña inválidos')
    # La validación de contraseña se hace antes de crear la cuenta.
    validate_password(password)
    with transaction.atomic():
        empresa = Empresa.objects.select_for_update().filter(pk=empresa_id, activa=True).first()
        if not empresa or not can_admin(request.user, empresa):
            return JsonResponse({'error': 'Sin acceso'}, status=403)
        if User.objects.filter(email__iexact=email).exists():
            return JsonResponse({'error': 'El correo ya corresponde a una cuenta. Usa Agregar miembro.'}, status=409)
        # User.username no admite más de 150 caracteres. Identificador generado y no adivinable.
        username = 'tocal-' + uuid.uuid4().hex
        user = User(username=username, email=email, name=nombre, rol='lectura',
                    is_staff=False, is_superuser=False, is_active=True)
        user.set_password(password)
        user.full_clean()
        user.save()
        membership = MembresiaEmpresa.objects.create(empresa=empresa, usuario=user)
        rol_asignado = None
        if rol_id:
            from .models import EmpresaObra, Rol
            from .services import assign_role

            rol_obj = Rol.objects.filter(pk=rol_id, empresa=empresa, activo=True).first()
            if not rol_obj:
                raise ValueError('El rol seleccionado no pertenece a la empresa o está inactivo')
            obra_obj = None
            if obra_id:
                enlace = EmpresaObra.objects.select_related('obra').filter(empresa=empresa, obra_id=obra_id).first()
                if not enlace:
                    raise ValueError('La obra seleccionada no pertenece a la empresa')
                obra_obj = enlace.obra
            assign_role(usuario=user, empresa=empresa, rol=rol_obj, obra=obra_obj)
            rol_asignado = rol_obj.codigo

        trabajador_id = None
        if crear_trabajador:
            from intranet.models import Trabajador

            partes = nombre.split()
            if len(partes) == 1:
                nombres_t, apellido_p, apellido_m = partes[0], '—', ''
            elif len(partes) == 2:
                nombres_t, apellido_p, apellido_m = partes[0], partes[1], ''
            else:
                nombres_t = ' '.join(partes[:-2])
                apellido_p = partes[-2]
                apellido_m = partes[-1]
            trab = Trabajador(
                empresa=empresa,
                usuario=user,
                nombres=nombres_t[:120],
                apellido_paterno=apellido_p[:120],
                apellido_materno=apellido_m[:120],
                rut=rut_trabajador,
                activo=True,
            )
            trab.full_clean()
            trab.save()
            trabajador_id = str(trab.pk)

        audit(empresa, request.user, 'usuario.crear', user,
              {'membresia_id': str(membership.pk), 'rol_asignado': rol_asignado, 'trabajador_id': trabajador_id})
    return JsonResponse({'usuario_id': str(user.pk), 'username': user.get_username(),
                         'email': user.email, 'membresia_id': str(membership.pk),
                         'rol_asignado': rol_asignado, 'trabajador_id': trabajador_id}, status=201)
