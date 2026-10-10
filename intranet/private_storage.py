"""Archivos privados locales o en un bucket privado de Supabase Storage.

Nunca se exponen credenciales a los clientes; cada lectura tiene autorización por obra.
"""
import re
from urllib.parse import quote
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
import httpx

VALID_KEY = re.compile(r"^[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$")

def validate_key(key):
    if not key or len(key) > 500 or not VALID_KEY.fullmatch(key) or any(part in (".", "..") for part in key.split("/")):
        raise ValidationError("Ruta de archivo inválida.")
    return key

def local_path(key):
    key = validate_key(key)
    root = settings.MEDIA_ROOT.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValidationError("Ruta de archivo inválida.")
    return path

def enabled():
    return settings.STORAGE_BACKEND == "supabase"

def _request(method, key, data=None, mime=None):
    key = validate_key(key)
    if not settings.SUPABASE_URL.startswith("https://") or not settings.SUPABASE_STORAGE_KEY or not settings.SUPABASE_STORAGE_BUCKET:
        raise RuntimeError("Configura Supabase Storage (URL, clave privada y bucket).")
    bucket = quote(settings.SUPABASE_STORAGE_BUCKET, safe="")
    relative = quote(key, safe="/")
    prefix = "object/authenticated" if method == "GET" else "object"
    url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/{prefix}/{bucket}/{relative}"
    # sb_secret_* no es un JWT: Supabase exige enviarlo únicamente en apikey.
    # Con el service_role antiguo (JWT), Authorization: Bearer sigue siendo válido.
    secret_key = settings.SUPABASE_STORAGE_KEY
    headers = {"apikey": secret_key}
    if not secret_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {secret_key}"
    if mime:
        headers["Content-Type"] = mime
        headers["x-upsert"] = "false"
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        response = client.request(method, url, headers=headers, content=data)
    response.raise_for_status()
    return response.content

def write_bytes(key, data, mime="application/octet-stream"):
    if enabled():
        _request("POST", key, data, mime)
    else:
        path = local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

def read_bytes(key):
    if enabled():
        return _request("GET", key)
    path = local_path(key)
    if not path.is_file():
        raise FileNotFoundError("Archivo privado no disponible")
    return path.read_bytes()

def delete(key):
    if enabled():
        _request("DELETE", key)
    else:
        local_path(key).unlink(missing_ok=True)
