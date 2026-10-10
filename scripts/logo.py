#!/usr/bin/env python3
"""Genera las variantes del logo Tocal desde seed-assets/logo-tocal.png (letras blancas en el original).
  public/logo-tocal.png         letras grafito → fondos claros (login, PDF)
  public/logo-tocal-blanco.png  letras blancas → fondos oscuros (rail)
  public/logo-marca.png         solo el ícono de edificios (cuadrado de marca, favicon)
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
src = Image.open(ROOT / "seed-assets" / "logo-tocal.png").convert("RGBA")
w, h = src.size
px = src.load()

# Letras: píxeles casi blancos con alfa en el tercio inferior (bajo la base naranja, y > 160 de 200).
oscuro = src.copy(); po = oscuro.load()
for y in range(int(h * 0.80), h):
    for x in range(w):
        r, g, b, a = po[x, y]
        if a > 0 and r > 200 and g > 200 and b > 200:
            po[x, y] = (58, 58, 58, a)
oscuro.save(ROOT / "public" / "logo-tocal.png")
src.save(ROOT / "public" / "logo-tocal-blanco.png")

# Marca: recorte del ícono (sin letras), centrado en lienzo cuadrado.
bbox = src.crop((0, 0, w, int(h * 0.80))).getbbox()
icono = src.crop((0, 0, w, int(h * 0.80))).crop(bbox)
lado = max(icono.size) + 8
marca = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
marca.paste(icono, ((lado - icono.width) // 2, (lado - icono.height) // 2), icono)
marca.save(ROOT / "public" / "logo-marca.png")
print("logo ok", src.size, icono.size)
