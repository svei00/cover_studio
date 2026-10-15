"""Lienzo en blanco: una captura base nueva (un PNG liso) para componer varias capturas con Pegar encima. Logica pura, sin Qt.

No es un tipo nuevo de documento: es una imagen como cualquier captura (se guarda en Imagenes/Cover Studio, el proyecto la
referencia y todo lo demas funciona igual: anotar, pegar encima, exportar)."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.annotate.errors import AnnotateError

MIN_SIDE = 64
MAX_SIDE = 8000
MAX_PIXELS = 36_000_000      # ~144 MB en RGBA; la vista previa y el pixelado trabajan sobre copias de esto
DEFAULT_COLOR = "#FFFFFF"
PRESETS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("Pantalla 1920 x 1080 (16:9)", (1920, 1080)),
    ("HD 1280 x 720 (16:9)", (1280, 720)),
    ("Cuadrado 1080 x 1080", (1080, 1080)),
    ("Vertical 1080 x 1350 (4:5)", (1080, 1350)),
)
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_size(size: object) -> tuple[int, int]:
    """(ancho, alto) validos o AnnotateError: enteros, de MIN_SIDE a MAX_SIDE y sin pasar de MAX_PIXELS en total."""
    if (not isinstance(size, (tuple, list)) or len(size) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in size)):
        raise AnnotateError("El tamano del lienzo debe ser un ancho y un alto en pixeles enteros.")
    width, height = size
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise AnnotateError(f"Cada lado del lienzo debe medir entre {MIN_SIDE} y {MAX_SIDE} px (pediste {width} x {height}).")
    if width * height > MAX_PIXELS:
        raise AnnotateError(
            f"{width} x {height} px son {width * height / 1e6:.0f} MP: mas de los {MAX_PIXELS / 1e6:.0f} MP que se pueden trabajar."
        )
    return width, height


def unique_png_path(folder: Path, prefix: str, now: datetime | None = None) -> Path:
    """<prefix>-<fecha>.png en `folder`; si ya existe, <prefix>-<fecha>-2.png, -3... (dos en el mismo segundo no se pisan:
    el proyecto REFERENCIA el archivo)."""
    stamp = f"{prefix}-{(now or datetime.now()):%Y%m%d-%H%M%S}"
    path = folder / f"{stamp}.png"
    n = 2
    while path.exists():
        path = folder / f"{stamp}-{n}.png"
        n += 1
    return path


def create_blank(size: tuple[int, int], color: str, folder: Path, now: datetime | None = None) -> Path:
    """Crea el PNG liso `lienzo-<fecha>.png` en `folder` (que se crea si falta) y devuelve su ruta. Escribe a un temporal y lo
    renombra: un fallo no deja un PNG a medias."""
    width, height = validate_size(size)
    if not isinstance(color, str) or not _HEX_RE.fullmatch(color):
        raise AnnotateError(f"Color de fondo no valido: {color!r} (usa #RRGGBB).")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = unique_png_path(folder, "lienzo", now)
        tmp = path.with_name(path.name + ".tmp")
        try:
            Image.new("RGB", (width, height), color).save(tmp, format="PNG")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise AnnotateError(f"No se pudo crear el lienzo en {folder}: {exc}") from exc
    return path
