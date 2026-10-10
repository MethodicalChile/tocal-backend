# Validaciones ejecutadas durante la migración

- Sintaxis Python (`compileall`) sin errores; **no equivale** a `manage.py check` ni a integración con BD.
- Sintaxis JavaScript (`node --check`) en scripts JS y 19 bloques `<script>` de componentes Vue: sin errores.
- Los estilos CSS, tipografía y archivo ECharts originales se conservaron sin transformaciones.
- Django enruta las operaciones del sistema por `/api/*` y retiene plantilla HTML solo para la generación interna del PDF, no para la interfaz pública.
- No se incluyen bases de datos antiguas, secretos reales, archivos privados ni los originales de `seed-assets`.

## Pendiente

- `npm install && npm run build` y pruebas de compilador Vue: la instalación npm falló por indisponibilidad de npm registry en el entorno de creación.
- `python manage.py check`, `python manage.py migrate` y suite de pruebas Django: dependencias Django no están instaladas en este entorno.
- Conexión real a Supabase, verificación RLS y bucket privado.
- Pruebas visuales, flujos de usuarios/roles, emisión PDF, importación, migración de datos y publicación con HTTPS.

**No clasificar como paridad exacta comprobada ni usar datos personales de producción hasta terminar QA.**
