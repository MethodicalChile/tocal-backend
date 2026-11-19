# TOCAL Backend (Django 5.2 + PostgreSQL / Supabase + RBAC)

Backend API REST para la administración multiempresa de obras de construcción, trabajadores, cargos, expedientes documentales, equipos/maquinaria, prevención de riesgos (PDR, capacitaciones, EPP, habilitación preventiva), alertas de vencimiento e indicadores ejecutivos.

---

## 1. Requisitos y Variables de Entorno (`T14.1`)

Crear archivo `.env` en `tocal-backend/` con las siguientes variables:

```env
# Seguridad y entorno
DJANGO_SECRET_KEY=reemplazar-por-clave-secreta-larga
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,tu-dominio.cl
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:5173,https://tu-dominio.cl
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://tu-dominio.cl

# Base de datos PostgreSQL / Supabase
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=tu_password
DB_HOST=db.tu-proyecto.supabase.co
DB_PORT=5432
DB_SSLMODE=require

# Almacenamiento privado (Supabase Storage S3 o almacenamiento privado local)
PRIVATE_STORAGE_BACKEND=supabase
SUPABASE_S3_ENDPOINT_URL=https://tu-proyecto.supabase.co/storage/v1/s3
SUPABASE_S3_ACCESS_KEY_ID=tu_access_key
SUPABASE_S3_SECRET_ACCESS_KEY=tu_secret_key
SUPABASE_S3_BUCKET_NAME=tocal-privado
SUPABASE_S3_REGION_NAME=sa-east-1
```

> **Nota para pruebas automatizadas (`T13.6`):** Durante la ejecución de `python manage.py test`, `config/settings.py` utiliza automáticamente SQLite en memoria (`:memory:`) y almacenamiento privado temporal local, garantizando aislamiento total respecto de la base de datos y bucket de desarrollo/producción.

---

## 2. Instalación, Migraciones y Verificación (`T14.2`)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Verificación de configuración y migraciones
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate

# Ejecución de la suite completa de pruebas
python manage.py test

# Levantar el servidor de desarrollo local (en http://127.0.0.1:8000)
python manage.py runserver
```

---

## 3. Trabajos Programados y Comandos de Operación (`T6.4`, `T4.4`, `T14.4`)

| Comando | Propósito | Frecuencia recomendada |
|---|---|---|
| `python manage.py detectar_vencimientos` | Analiza documentos aprobados de trabajadores, empresa y equipos según `ConfiguracionAlertaEmpresa` (`30/15/7` días), crea/actualiza `AlertaVencimiento` y marca como `vencido` los documentos cuya `fecha_vencimiento < hoy`. | Diario (`06:00 AM`) |
| `python manage.py normalizar_documentos_aprobados --dry-run` | Detecta documentos en estado `aprobado` sin archivos de evidencia asociados. Sin `--dry-run`, los revierte a `en_revision` dejando trazabilidad en `RevisionDocumentoTrabajador` y `SecurityAuditEvent`. | En despliegues o auditorías |

---

## 4. Arquitectura de Seguridad, RBAC y Privacidad (`Etapas 1 y 12`)

1. **Aislamiento multiempresa y por obra:**
   - Todos los endpoints bajo `/api/empresas/<empresa_id>/...` y `/api/documentos/empresas/<empresa_id>/...` verifican membresía activa (`UsuarioEmpresa`) y permisos efectivos (`Permiso`) en el backend.
   - Si un rol está restringido a obras específicas (`UsuarioEmpresaRol.obra_id`), las consultas y escrituras se filtran mediante `authorized_obra_ids(user, empresa)` y `user_can_access_company_obra`.
2. **Almacenamiento privado y validación de archivos (`intranet/private_storage.py`):**
   - Ningún archivo se sirve mediante URLs públicas directas; toda descarga pasa por endpoints autenticados con respuesta `FileResponse(..., as_attachment=True)` y cabeceras `Cache-Control: private, no-store` y `X-Content-Type-Options: nosniff`.
   - Se validan extensión, MIME, firma binaria (magic bytes para PDF, PNG, JPEG, WEBP y contenedores Office OpenXML), tamaño máximo (25 MB) y sanitización de nombre de archivo.
3. **Protección de datos sensibles (Ley 19.628 / 21.719):**
   - El campo `rut` de `Trabajador` solo se expone a usuarios con el permiso explícito `empleados.ver_sensibles`.
   - Toda consulta a fichas con datos sensibles, cambio de rol/membresía, aprobación/rechazo documental y descarga de evidencias queda registrada en `SecurityAuditEvent` (consultable en `/api/empresas/<empresa_id>/auditoria/`).

---

## 5. Estrategia de Respaldos y Recuperación (`T14.3`)

- **Base de datos PostgreSQL / Supabase:** Respaldo diario automatizado (PITR / snapshots diarios con retención mínima de 7 a 30 días) más `pg_dump --format=custom` previo a cada ventana de migración productiva.
- **Bucket privado de evidencias (`tocal-privado`):** Sincronización incremental de objetos mediante S3 replication o backup periódico de los prefijos `documentos/`, `documentos_empresa/`, `documentos_equipo/` e `intranet/`.
- **Integridad:** Las tablas operacionales e históricas utilizan `on_delete=models.PROTECT` y desactivación lógica (`activo=False`) para impedir pérdida accidental de trazabilidad.

---

## 6. Matriz de Alcance Funcional Implementado (`Etapa 15`)

| Documento / Levantamiento en `/documentos` | Estado | Implementación en TOCAL |
|---|---|---|
| `Organigrama Tocal.pdf` y 12 `Perfiles de Cargo (*.doc)` | **Implementado** | Catálogo empresarial de cargos (`CargoEmpresa`) + endpoint semilla `POST /api/empresas/<empresa_id>/cargos/catalogo-tocal` con los 15 cargos levantados (Gerente General, Jefe de Obra, Prevencionista, Bodeguero, Maestro Primera/Segunda, Soldador, Operador, etc.). |
| `Levantamiento proceso de Informes de Prevención.docx` | **Implementado** | Módulo PDR por obra (`/obras/:obraId/pdr`), cálculo de cumplimiento documental y preventivo por trabajador/obra/equipo, capacitaciones (`TipoCapacitacion`, `CapacitacionTrabajador`), entrega de EPP (`CategoriaEPP`, `EntregaEPP`) y estado de habilitación preventiva (`habilitado`, `condicionado`, `no_habilitado`). |
| Expediente documental de trabajadores, empresa y equipos | **Implementado** | Aprobación segura (prohibido aprobar sin archivo válido), historial de revisiones, cálculo automático de cumplimiento (`al_dia`, `por_vencer`, `incumplimiento`), alertas configurables y exportación CSV/Excel. |
