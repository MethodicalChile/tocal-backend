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
    """Alta de usuario nuevo + membresía, sin otorgar roles ni permisos automáticamente."""
    data = payload(request)
    if set(data) != {'nombre', 'email', 'password'}:
        raise ValueError('Se requieren nombre, email y password')
    nombre = str(data['nombre']).strip()
    email = str(data['email']).strip().lower()
    password = data['password']
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
        audit(empresa, request.user, 'usuario.crear', user,
              {'membresia_id': str(membership.pk)})
    return JsonResponse({'usuario_id': str(user.pk), 'username': user.get_username(),
                         'email': user.email, 'membresia_id': str(membership.pk)}, status=201)
