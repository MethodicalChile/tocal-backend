# Validación de la separación

Auditoría realizada al preparar esta entrega:

- Todos los **38 archivos** de `templates/` en el frontend tienen SHA-256 idéntico a los de `Tocal-intranet` original.
- Los **14 archivos** originales de `static/` tienen SHA-256 idéntico a la copia bajo `tocal-frontend/static/`.
- Los **8 archivos** de `public/` tienen SHA-256 idéntico a los originales. Los estáticos se copian también bajo `site/static/` para publicarlos sin transpilar.
- No se copiaron plantillas, CSS o JS de la UI al backend. El logo utilizado dentro del PDF se conserva en `pdf-assets/logo-tocal.png` porque la generación documental corresponde al backend.
- `python -m compileall` no detectó errores sintácticos Python en el backend.
- La configuración Nginx superó `nginx -t` y una prueba HTTP local: archivo HTML remoto rechazado con 403 sin token, devuelto con 200 con token, JS y logo servidos con 200.

**No verificado en esta entrega:** ejecución de tests Django completos, integración con Supabase real, migración de datos productivos, generación de PDFs en el contenedor, renderizados pixel a pixel en navegador y deployment HTTPS. Esas comprobaciones requieren dependencias de Python, credenciales y un entorno real. No se debe afirmar que la aplicación ya está desplegada o certificada.

## Rutas conservadas

La configuración original `intranet/urls.py` está íntegra: login/logout, panel general, obra, prevención, avance, registros de pago/adicionales/RDI, fotos, informes, PDF/impresión y ventas. En la lógica Django solo se adaptaron las operaciones de archivos a Supabase, la localización de plantillas y la carga de logos en PDF.

## QA mínimo previo a producción

1. Con credenciales reales de Supabase, ejecutar `migrate`, `harden_supabase`, `check --deploy` y verificar acceso denegado para `anon`.
2. Registrar usuarios por rol, probar obra autorizada y ajena, escritura negada a lectura/experto en módulos ajenos.
3. Login/logout, dashboard, curvas, semanas, checklist, formularios, RDI, fotos y edición.
4. Emitir, descargar, reabrir y previsualizar informe PDF con fotografías del bucket privado.
5. Importación de Excel de ventas y edición, filtros, búsqueda y paginación.
6. Revisar carga de logo, tipografía y gráficos y comparar capturas móvil/escritorio del original y de la separación.
7. Verificar TLS/CSRF/`no-store`, rotación de secretos, restauración de backups y políticas de datos.

## Pruebas adicionales (revisión final)

- `scripts/validate_split.py`: **127 controles** superados.
- `node --check`: todos los JavaScript originales revisados.
- Nginx (`nginx -t`): OK; endpoint de plantillas con token ausente/erróneo **403**, token válido **200**, logo y JavaScript **200**.
- Smoke test de Supabase Storage con cliente HTTP simulado: `sb_secret_*` se envía solamente en `apikey`, `service_role` legado se envía también en `Authorization: Bearer`; rutas con traversal se rechazan.
- Se corregió el import de `httpx` en el manejo de excepciones de descargas privadas.
- `harden_supabase` protege tablas `django_*`, `auth_*`, `tocal_*` y sus secuencias.

**Todavía no verificado:** tests Django completos ni integración real con Supabase, pues las dependencias Django no pudieron instalarse en este entorno aislado sin acceso a PyPI, y no se proporcionaron credenciales de Supabase.
