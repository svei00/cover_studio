"""Medicion de texto con Pillow/FreeType, sin Qt. Cae a una heuristica si la
fuente no se encuentra."""

from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

_REGULAR = "arial.ttf"
_BOLD = "arialbd.ttf"
_FALLBACK_EM = {True: 0.58, False: 0.52}


@lru_cache(maxsize=64)
def _load_font(size_px: int, bold: bool) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(_BOLD if bold else _REGULAR, size_px)
    except OSError:
        return None


def measure_line(text: str, size: float, bold: bool) -> float:
    """Ancho en px de una linea de texto al tamano dado."""
    if not text:
        return 0.0
    font = _load_font(max(1, round(size)), bold)
    if font is None:
        return len(text) * size * _FALLBACK_EM[bold]
    return float(font.getlength(text))
