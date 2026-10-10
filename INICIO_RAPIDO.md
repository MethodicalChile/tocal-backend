# Tocal: dos repositorios, backend Django + frontend Vue 3

```
tocal-proyecto/
├── tocal-backend/     Django REST, PostgreSQL Supabase, Supabase Storage
├── tocal-frontend/    Vue 3, Vite, CSS/JS visual, Nginx
└── compose.yml        Ambos servicios conectados
```

## 1. Supabase

Crear proyecto PostgreSQL, conservar cadena de conexión Pooler y clave privada `sb_secret_*`; crear bucket privado `tocal-privado`. No agregar esas claves al frontend. Configurar SSL para Postgres.

## 2. Variables del backend

Editar `tocal-backend/.env` con `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `STORAGE_BACKEND=supabase`, `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS`. Ejecutar `python tocal-backend/scripts/prepare_env.py` para generar la clave Django.

Desarrollo local: `DJANGO_DEBUG=1` por HTTP. Producción: `DJANGO_DEBUG=0`, HTTPS, dominio, TLS en proxy/ingress y certificados. El backend debe recibir cabecera `X-Forwarded-Proto` únicamente de proxies controlados.

## 3. Ejecutar

```bash
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py harden_supabase
docker compose exec backend python manage.py createsuperuser
```

Front: `http://localhost:8080` durante desarrollo; back: `/api/*` vía Nginx. La cuenta se crea con `createsuperuser`; utiliza un usuario real con email y permisos en Django, asignado a obras según su rol.

Para desarrollo sin Docker:

```bash
cd tocal-backend
pip install -r requirements.txt
python scripts/prepare_env.py
python manage.py migrate
python manage.py runserver 8000
# Otra terminal:
cd ../tocal-frontend
cp .env.example .env
npm install
npm run dev
```

## 4. Pruebas imprescindibles antes de publicar

Comprobar inicio/cierre de sesión, aislamiento entre obras, crear/editar/delete registros, semanas PDR, checklist, punto de curva, subida de fotografía, emisión/descarga PDF, importación XLSX, ventas y derecho de acceso a datos. Comparar visualmente todas las vistas originales. Revisar `tocal-backend/docs/PROTECCION_DATOS.md`.

## Limitaciones declaradas

Se incluyeron componentes Vue y API para las funcionalidades principales, conservando cálculos y CSS originales, pero **no se ha ejecutado una verificación extremo a extremo ni se ha conectado un Supabase real**. La instalación npm no pudo completarse en el entorno de creación, por lo que no afirmamos que `npm run build` haya pasado. La paridad exacta de diseño y todos los casos funcionales requieren QA.
