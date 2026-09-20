"""Operaciones de bitmap con Pillow: carga y pixelado. El pixelado se aplica
al bitmap antes de cualquier otra cosa, asi un dato anonimizado nunca
aparece en el SVG ni dentro de una lupa."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from core.annotate.errors import AnnotateError
from core.annotate import lens
from core.annotate.model import Annotation, Magnifier, Redaction, Spotlight
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


def active_spotlight(items: Sequence[Annotation]) -> Spotlight | None:
    """El foco que cuenta: solo hay uno por documento (si un proyecto trae varios, el ultimo)."""
    found = None
    for item in items:
        if isinstance(item, Spotlight):
            found = item
    return found


def _zone_mask(size: tuple[int, int], spot: Spotlight) -> Image.Image:
    """Mascara 'L' (255 dentro de la zona del foco). Con esquinas redondeadas se dibuja a 4x para que el borde salga
    suave."""
    mask = Image.new("L", size, 0)
    x0 = max(0, int(round(spot.rect.x)))
    y0 = max(0, int(round(spot.rect.y)))
    x1 = min(size[0], int(round(spot.rect.right)))
    y1 = min(size[1], int(round(spot.rect.bottom)))
    if x1 <= x0 or y1 <= y0:
        return mask
    w, h = x1 - x0, y1 - y0
    radius = min(spot.corner, w / 2, h / 2)
    if radius < 0.5:
        mask.paste(255, (x0, y0, x1, y1))
        return mask
    big = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 4, fill=255)
    mask.paste(big.resize((w, h), Image.LANCZOS), (x0, y0))
    return mask


def apply_spotlight(img: Image.Image, items: Sequence[Annotation]) -> Image.Image:
    """Imagen con el foco aplicado: fuera de la zona se desenfoca y/o se oscurece (negro con opacidad `dim`); la zona
    queda intacta. Sin foco, o sin efecto (dim 0 y blur 0), devuelve la misma imagen. Va DESPUES del pixelado y de
    las lupas: los datos pixelados siguen pixelados y las lupas no salen oscurecidas."""
    spot = active_spotlight(items)
    if spot is None or (spot.dim <= 0 and spot.blur <= 0):
        return img
    outside = img
    if spot.blur > 0:
        outside = outside.filter(ImageFilter.GaussianBlur(spot.blur))
    if spot.dim > 0:
        shade = Image.new("RGBA", img.size, (0, 0, 0, round(255 * min(1.0, spot.dim))))
        outside = Image.alpha_composite(outside, shade)
    return Image.composite(img, outside, _zone_mask(img.size, spot))


def lens_crops(img: Image.Image, items: Sequence[Annotation]) -> dict[str, Image.Image]:
    """Un recorte por lupa, ampliado con LANCZOS al tamano de su lente. Se toma de
    la imagen que se le pase: debe ser la YA pixelada, para que un dato
    anonimizado no reaparezca dentro de una lupa."""
    crops: dict[str, Image.Image] = {}
    for item in items:
        if not isinstance(item, Magnifier):
            continue
        width, height = lens.lens_size(item)
        size = (max(1, round(width)), max(1, round(height)))
        crops[item.id] = img.crop(lens.crop_box(item)).resize(size, Image.LANCZOS)
    return crops
