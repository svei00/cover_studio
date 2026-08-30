"""Operaciones de bitmap con Pillow: carga y pixelado. El pixelado se aplica
al bitmap antes de cualquier otra cosa, asi un dato anonimizado nunca
aparece en el SVG ni dentro de una lupa."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from core.annotate.errors import AnnotateError
from core.annotate.model import Annotation, Redaction
from core.geometry import SUPPORTED_PHOTO_SUFFIXES


def load_image(path: Path) -> Image.Image:
    """Abre la captura como RGBA, respetando la orientacion EXIF."""
    if not path.exists():
        raise AnnotateError(f"No se encontro la captura: {path}")
    if path.suffix.lower() not in SUPPORTED_PHOTO_SUFFIXES:
        raise AnnotateError(
            f"Formato no soportado ({path.suffix or 'sin extension'}). Usa png, jpg, jpeg o webp."
        )
    try:
        with Image.open(path) as img:
            return ImageOps.exif_transpose(img).convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise AnnotateError(f"El archivo no es una imagen valida: {path.name}") from exc


def apply_redactions(img: Image.Image, items: Sequence[Annotation]) -> Image.Image:
    """Devuelve una copia con cada Redaction pixelada. Irreversible: la zona se
    reduce a bloques de color promedio y se amplia sin suavizar."""
    out = img.copy()
    for item in items:
        if not isinstance(item, Redaction):
            continue
        x0 = max(0, int(item.rect.x))
        y0 = max(0, int(item.rect.y))
        x1 = min(out.width, int(round(item.rect.right)))
        y1 = min(out.height, int(round(item.rect.bottom)))
        if x1 <= x0 or y1 <= y0:
            continue
        w, h = x1 - x0, y1 - y0
        block = max(1, item.block)
        region = out.crop((x0, y0, x1, y1))
        small = region.resize((max(1, round(w / block)), max(1, round(h / block))), Image.BOX)
        out.paste(small.resize((w, h), Image.NEAREST), (x0, y0))
    return out
