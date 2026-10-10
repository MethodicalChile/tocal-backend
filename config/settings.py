import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or os.getenv("BETTER_AUTH_SECRET")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "Configura DJANGO_SECRET_KEY o usa DJANGO_DEBUG=1 para desarrollo local."
        )
    SECRET_KEY = "django-insecure-local-development-only-tocal"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",")
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if x]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "intranet",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "intranet.security.PrivateNoCacheMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}" if DEBUG else "")
if not database_url:
    raise ImproperlyConfigured("DATABASE_URL es obligatorio con DJANGO_DEBUG=0.")
if not DEBUG and not database_url.startswith(("postgres://", "postgresql://")):
    raise ImproperlyConfigured("Producción requiere PostgreSQL (Supabase).")
DATABASES = {"default": dj_database_url.parse(database_url, conn_max_age=0)}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = os.getenv("DB_SSLMODE", "require")
    # Para conexiones vía transaction pooler de Supabase: no guardar conexiones de sesión.
    DATABASES["default"]["CONN_MAX_AGE"] = 0
AUTH_USER_MODEL = "intranet.User"
AUTHENTICATION_BACKENDS = ["intranet.auth.EmailBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{v}"}
    for v in [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]
]
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Los CSS, JS, iconos y logos públicos son responsabilidad del frontend.
STATICFILES_DIRS = []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_ROOT = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
# Preferir claves sb_secret_* modernas; service_role JWT solo por compatibilidad.
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_STORAGE_KEY = (
    SUPABASE_SECRET_KEY if SUPABASE_SECRET_KEY and not SUPABASE_SECRET_KEY.startswith("REEMPLAZAR")
    else SUPABASE_SERVICE_ROLE_KEY
)
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "tocal-privado")


PRIVACY_CONTACT_EMAIL = os.getenv("PRIVACY_CONTACT_EMAIL", "privacidad@tocal.cl")
if not DEBUG and STORAGE_BACKEND != "supabase":
    raise ImproperlyConfigured("Producción requiere STORAGE_BACKEND=supabase para evitar pérdida de fotos y PDF.")
if STORAGE_BACKEND not in ("local", "supabase"):
    raise ImproperlyConfigured("STORAGE_BACKEND debe ser local o supabase.")
# Los archivos privados requieren sesión y permiso sobre la obra.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Protección por defecto. En producción configurar dominio, TLS y cabeceras del proxy.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "28800"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if os.getenv("TRUST_PROXY_HEADERS", "0") == "1" else None

if not DEBUG:
    if SECRET_KEY.startswith(("REEMPLAZAR", "django-insecure")) or len(SECRET_KEY) < 40:
        raise ImproperlyConfigured("Genera DJANGO_SECRET_KEY largo y aleatorio para producción.")
    if not SUPABASE_URL.startswith("https://") or not SUPABASE_STORAGE_KEY or SUPABASE_STORAGE_KEY.startswith("REEMPLAZAR"):
        raise ImproperlyConfigured("Configura las credenciales privadas de Supabase antes de desplegar.")
