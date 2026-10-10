#!/usr/bin/env python3
"""Crea un .env privado para Django, sin imprimir secretos."""
from pathlib import Path
import os
import secrets

base = Path(__file__).resolve().parents[1]
path = base / '.env'
if not path.exists():
    path.write_text((base / '.env.example').read_text(encoding='utf8'), encoding='utf8')
lines = path.read_text(encoding='utf8').splitlines()
changed = False
for i, line in enumerate(lines):
    if line.startswith('DJANGO_SECRET_KEY='):
        value = line.split('=', 1)[1]
        if not value or value.startswith('REEMPLAZAR') or value.startswith('django-insecure'):
            lines[i] = 'DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64)
            changed = True
if not any(line.startswith('DJANGO_SECRET_KEY=') for line in lines):
    lines.append('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))
    changed = True
if changed:
    path.write_text('\n'.join(lines) + '\n', encoding='utf8')
if os.name == 'posix':
    path.chmod(0o600)
print('Configuración preparada. Completa DATABASE_URL y credenciales Supabase antes de iniciar.')
