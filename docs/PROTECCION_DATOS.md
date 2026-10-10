# Protección de datos Tocal (Chile) — preparación operativa

**Normativa:** Ley N° 19.628 actualmente aplicable; Ley N° 21.719 (publicada el 13/12/2024, entrada en vigor 01/12/2026, según BCN). Esta lista NO equivale a certificación de conformidad, asesoría jurídica ni reemplaza una revisión por encargado de datos/abogado.

## Protecciones técnicas incluidas

| Aspecto | Implementación | Verificación necesaria |
|---|---|---|
| Control de acceso | Sesión Django, autenticación por correo y autorización por obra/rol | Pruebas con cada rol; desactivar usuarios que salen de la empresa |
| Fotografías/PDF | Supabase bucket **privado**; acceso por vista backend con permiso por obra | Confirmar bucket privado y auditar API de Storage |
| Protección de BD | ORM Django, TLS PostgreSQL, `harden_supabase` revoca anon/authenticated y activa RLS sin políticas | Probar anon sin privilegios; desactivar Data API pública si no se usa |
| Contraseñas | Hash Django, migración de hashes scrypt heredados en primer acceso | Política de fuerza, MFA/SSO si aplica |
| Sesión y web | Cookies seguras/HttpOnly/SameSite, CSRF, HTTPS, HSTS, no-store, clickjacking, proxy privado | Verificar terminación TLS, dominio, orígenes CSRF, proxy y cabeceras |
| Solicitudes de titulares | `SolicitudPrivacidad` registra solicitudes y estados; cada usuario ve únicamente sus solicitudes | Designar responsable para revisar identidad, alcance, plazos y respuesta formal |
| Minimización y trazabilidad | Endpoints JSON solo devuelven datos acotados y filtrados por asignación; no se exponen secretos al cliente; Nginx/Gunicorn omiten access logs de URL por defecto | Diseñar auditoría del acceso administrativo sin datos personales ni URLs sensibles |

## Tareas organizativas obligatorias antes de producción

1. **Inventario de datos:** usuarios, correos, RUT, nóminas/dotación, clientes, montos financieros, fotografías de personas, datos en informes, importaciones XLSX y metadatos. Definir responsable, finalidades y bases de licitud específicas de cada finalidad.
2. **Aviso de privacidad real:** identificar al responsable de tratamiento, datos de contacto, finalidades, bases legales, destinatarios, lugar/país de alojamiento, plazos de conservación, derechos y canales de atención. El campo `PRIVACY_CONTACT_EMAIL` solo configura un contacto: **no genera un aviso legal válido**.
3. **Contratos y transferencia internacional:** revisar las condiciones de tratamiento y subencargados de Supabase, región seleccionada, backups, soporte, contratos y normas aplicables a transferencias internacionales.
4. **Derechos:** definir procedimiento verificable para acceso, rectificación, supresión, bloqueo, oposición y portabilidad, con plazos, excepciones de conservación y acuse formal. Las solicitudes se registran pero no se resuelven automáticamente.
5. **Retención y borrado:** fijar tiempos por tipo de dato y obligación contractual/tributaria; diseñar purga de fotos, PDF, exports, logs y backups. El borrado original de fotografías elimina su registro, **pero conserva el archivo** para informes emitidos; esto requiere una justificación de conservación y un proceso de purga segura posterior. No afirmar supresión completa con el botón de la UI.
6. **Incidentes de seguridad:** canal de incidentes, detección, aislamiento, restauración, notificaciones si corresponden, evidencias y simulacros. Definir administrador y suplentes.
7. **Acceso privilegiado:** MFA para admins, roles mínimos, revisión de accesos periódica y cambio/rotación de claves. Aplicar rate limiting/WAF para ataques por fuerza bruta (no implementado como control distribuido en este proyecto).
8. **Pruebas:** pentest y evaluación de amenazas, prueba de permisos entre obras, prueba de restauración, verificación de TLS, auditoría de logs sin datos personales, validación de carga de imágenes y planillas.
9. **Producción:** excluir cuentas/contraseñas de demo, planillas reales y archivos `.env` de repositorios y builds públicos. `seed-assets/` contiene clientes identificables del paquete entregado; está excluido de Git y Docker y no debe compartirse públicamente.

## Privacidad en Supabase

- No colocar URL de conexión PostgreSQL ni `sb_secret_*` o `service_role` legado en frontend, Vite ni Cloudflare Pages.
- Solo las cuentas administrativas del backend consultan PostgreSQL; Django aplica autorización por rol y obra.
- Después de `migrate`, ejecutar `harden_supabase` y verificar la seguridad con credenciales anon reales; reejecutar después de cambios en modelos.
- Crear bucket `tocal-privado` como `private`. Las fotos y los PDF se envían por la API Storage desde backend; no se publican URL firmadas permanentes.
- Habilitar SSL, backups y alertas; decidir la región de residencia de datos conforme a las exigencias contractuales.

**Referencias oficiales:** https://www.bcn.cl/leychile/Navegar?idNorma=1209272 y https://supabase.com/docs/guides/database/connecting-to-postgres

**Respaldo local:** `backup_database` (función heredada) está bloqueado por defecto en producción porque genera un dump sin cifrar. Para respaldos reales utiliza herramientas/servicios con cifrado y una política verificable; forzar `ALLOW_LOCAL_UNENCRYPTED_BACKUP=1` asume un riesgo explícito y no se recomienda.
