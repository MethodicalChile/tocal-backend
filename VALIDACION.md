# Validaciones ejecutadas en `tocal-backend` y `tocal-frontend`

- **Integridad Django (`python manage.py check`)**: `System check identified no issues (0 silenced)`.
- **Suite completa de pruebas Backend (`python manage.py test`)**: **99 pruebas automatizadas aprobadas (`OK`)** cubriendo:
  - Aislamiento multiempresa (`Empresa`, `EmpresaObra`, `MembresiaEmpresa`) y matriz RBAC por obra.
  - Catálogo oficial de 21 cargos TOCAL, fichas de trabajadores, validación de RUT Módulo 11 y carga masiva de cuadrillas CSV/Excel.
  - Gestión documental versionada con huella criptográfica `SHA-256`, bloqueo de aprobación sin evidencia adjunta y almacenamiento privado.
  - Prevención de Riesgos DS 44: Kit «Hombre Nuevo» (`RF-06`), difusión de PTS y prueba de comprensión de 3 preguntas (`RF-07`/`RF-08`), Charla Diaria 5 Minutos / AST masiva, entrega de EPP con firma digital en pantalla (`RF-09`), Protocolos MINSAL (`PLANESI`, `PREXOR`, `RUVS`, `TMERT`) y Dossier FUF / DS 44 (`FUF-01` a `FUF-08`).
  - Motor de alertas de vencimiento (`60, 30, 15, 7` días) y consulta rápida en terreno con lector QR de Cédula de Identidad / Credencial `TOCAL-XXXX` (`RF-15`).
  - Derechos ARCO+, eliminado lógico (`Soft Delete` + `PROTECT`) y portabilidad electrónica en JSON y CSV bajo la Ley N° 21.719.
- **Pruebas unitarias Frontend (`node --test tests/frontend.test.mjs`)**: **4 de 4 pruebas aprobadas (`pass 4, fail 0`)**.
- **Compilación de producción Frontend (`vite build`)**: Build limpio de los módulos Vue 3 + Vite generado en `dist/`.

## Requisitos operativos previos a puesta en producción real

- Configurar variables de entorno productivas (`DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` robusto, `DATABASE_URL` PostgreSQL con SSL, `STORAGE_BACKEND=supabase` y bucket privado `tocal-privado`).
- Ejecutar `python manage.py migrate` y `python manage.py harden_supabase` sobre la base de datos de producción.
- Completar las tareas organizativas descritas en `docs/PROTECCION_DATOS.md` (designación de responsable de privacidad, contratos de subencargados y políticas de retención/purga).
