-- Ejecutar en el SQL Editor de Supabase solo en un proyecto propio.
-- El bucket NO es público. Nadie debe acceder a archivos directamente con anon.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'tocal-privado', 'tocal-privado', false,
    104857600, ARRAY['image/jpeg', 'application/pdf']::text[]
)
ON CONFLICT (id) DO UPDATE
SET public = false, file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Intencionalmente NO crear políticas SELECT/INSERT/UPDATE/DELETE para anon/authenticated
-- sobre storage.objects: el backend usa su credencial privada, controlando permisos por obra.
-- La URL del bucket no da permiso de lectura si el bucket es privado.
