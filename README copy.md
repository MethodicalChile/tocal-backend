# TOCAL · Backend Django (API REST)

Backend de la intranet Tocal migrado a Django 5.2 + JSON REST, **sin vistas HTML del sistema**. Mantiene modelos, migraciones, formularios, permisos, reglas de negocio, procesos Excel, fotos y emisión PDF. El PDF se produce internamente mediante una plantilla Django de documento; la interfaz de usuario se sirve únicamente en el repositorio Vue.

## Configuración de Supabase

1. Crear proyecto PostgreSQL en Supabase y un bucket privado `tocal-privado` para fotografías e informes.
2. `cp .env.example .env` si `.env` todavía no existe.
3. Ejecutar `python scripts/prepare_env.py` para generar un `DJANGO_SECRET_KEY` aleatorio.
4. Completar `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (clave privada `sb_secret_*`), `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`.
5. Para localhost, `DJANGO_DEBUG=1`; para producción, `DJANGO_DEBUG=0`, TLS válido y `STORAGE_BACKEND=supabase`.

No usar `sb_secret_*` en frontend ni en código JavaScript.

## Inicio local

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python scripts/prepare_env.py
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

Ejecutar luego `npm run dev` desde `../tocal-frontend`.

## API

- `GET /api/csrf` y `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/session`
- `GET /api/dashboard` y `GET /api/obras/{id}/resumen`
- `GET /api/obras/{id}/pdr`, `POST /pdr/semanas`, `PUT /pdr/semanas/{semana}/dotacion|checklist`
- `GET /api/obras/{id}/avance`, `POST /avance/curvas/{curva}/puntos`
- `GET /api/obras/{id}/registros/{edp|adicionales|rdi|actividad}`; `POST .../nuevo`, `GET|PUT|DELETE .../{pk}`
- `GET /api/obras/{id}/fotos`, `POST .../fotos/subir`, `GET /api/files/{key}`
- `GET|POST /api/obras/{id}/informes`, `GET|PUT|POST|DELETE .../informes/{id}`, `GET .../pdf`
- `GET /api/ventas`, `GET /api/ventas/documentos`, `POST /api/ventas/importar`
- `GET|POST /api/privacidad/solicitudes` (derechos de titulares, sujetos a revisión humana).

Todas las lecturas privadas exigen sesión; las acciones de edición exigen el rol correspondiente. Autorización de obra en cada endpoint. La sesión utiliza cookie HttpOnly/SameSite y las mutaciones exigen CSRF. Vite/Nginx proxy evitan CORS innecesario.

## Migraciones y endurecimiento en Supabase

```bash
python manage.py migrate
python manage.py harden_supabase
```

**Importante:** `harden_supabase` quita privilegios Data API de `anon` y `authenticated` sobre las tablas Django, activa RLS y requiere pruebas posteriores. Ejecutar en QA antes de producción y después de cada migración. Ver `docs/PROTECCION_DATOS.md`.

## Protección de datos

No se incluyen `seed-assets` ni fotografías reales del ZIP original en estos proyectos. La BD nueva no se llena automáticamente con datos antiguos. No publicar `.env`, respaldos, XLSX ni fotos. Se requiere avisos de privacidad, contrato con proveedores, evaluación de transferencias, MFA, políticas de retención, auditoría y respuesta a incidentes. Las solicitudes de privacidad **no producen eliminaciones automáticas**.

## Estado de la entrega

Migración de código e interfaz API preparada. **No está certificada como una réplica exacta ni como lista para producción** hasta ejecutar pruebas integrales con Supabase real, verificar el frontend compilado, contrastar la interfaz visual y validar los permisos por rol.
