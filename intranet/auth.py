"""Acceso por correo y conversión de contraseñas heredadas tras el primer ingreso."""

import hashlib
import hmac
import unicodedata

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import make_password

from .models import User


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        user = User.objects.filter(email__iexact=username.strip()).first()
        if user is None:
            make_password(password)
            return None
        if not self.user_can_authenticate(user):
            return None
        if user.check_password(password):
            return user
        if user.legacy_password:
            try:
                salt, expected = user.legacy_password.split(":", 1)
                actual = hashlib.scrypt(
                    unicodedata.normalize("NFKC", password).encode(),
                    salt=salt.encode(),
                    n=16384,
                    r=16,
                    p=1,
                    dklen=64,
                    maxmem=128 * 1024 * 1024,
                ).hex()
                if hmac.compare_digest(actual, expected):
                    user.set_password(password)
                    user.legacy_password = ""
                    user.save(update_fields=["password", "legacy_password"])
                    return user
            except (ValueError, TypeError):
                pass
        return None
