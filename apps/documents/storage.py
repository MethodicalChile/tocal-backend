"""Validación endurecida de archivos de evidencia y respuestas privadas seguras (Etapa 12).

Centraliza la verificación de firma real (magic bytes), extensión, tamaño máximo,
sanitización de nombre original, generación de claves privadas sin PII y encabezados
de seguridad en descargas.
"""
import hashlib
import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.http import FileResponse
from django.utils.text import get_valid_filename

from intranet import private_storage as default_private_storage

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def detect_mime_and_extension(data: bytes):
    """Verifica magic bytes reales del binario."""
    if not data:
        return None, None
    if data.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in data[-32:]:
        return "image/png", ".png"
    return None, None


def validate_uploaded_evidence(upload):
    """Valida tamaño, magic bytes, extensión y nombre seguro de un archivo subido.

    Devuelve (data, mime, extension, safe_filename, sha256) o lanza ValueError.
    """
    max_size = min(
        getattr(settings, "DOCUMENTS_MAX_FILE_SIZE", 10 * 1024 * 1024),
        10 * 1024 * 1024,
    )
    if not upload or not upload.size or upload.size > max_size:
        raise ValueError("Archivo vacío o demasiado grande (máximo 10 MB).")
    data = upload.read(max_size + 1)
    if not data or len(data) > max_size:
        raise ValueError("Archivo vacío o demasiado grande.")
    mime, extension = detect_mime_and_extension(data)
    if mime is None:
        raise ValueError("Solo se aceptan PDF, PNG o JPEG válidos.")
    raw_name = Path(upload.name or "archivo").name
    filename = get_valid_filename(raw_name)[:180]
    if not filename:
        filename = "archivo" + extension
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Extensión no permitida.")
    if ALLOWED_EXTENSIONS[suffix] != mime:
        raise ValueError("La extensión no coincide con el contenido.")
    digest = hashlib.sha256(data).hexdigest()
    return data, mime, extension, filename, digest


def build_storage_key(prefix: str, empresa_id, entity_id, extension: str) -> str:
    """Construye una clave privada no adivinable y libre de datos personales (PII)."""
    clean_prefix = prefix.strip("/")
    return f"{clean_prefix}/{empresa_id}/{entity_id}/{uuid4().hex}{extension}"


def build_private_file_response(data: bytes, *, mime: str, filename: str) -> FileResponse:
    """Construye respuesta de descarga privada con cabeceras de seguridad reforzadas."""
    response = FileResponse(
        BytesIO(data),
        content_type=mime,
        as_attachment=True,
        filename=filename,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response

