"""Operaciones de bitmap con Pillow: carga, imagenes pegadas, pixelado y foco. Orden del pipeline: captura -> imagenes
pegadas -> pixelado -> recortes de lupa -> foco -> anotaciones. El pixelado va antes de lo demas (menos de lo pegado), asi
un dato anonimizado nunca aparece en el SVG ni dentro de una lupa."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from core.annotate.errors import AnnotateError
from core.annotate import lens, style
from core.annotate.model import Annotation, ImageOverlay, Magnifier, Redaction, Spotlight
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


_SOURCES: dict[str, tuple[int, int, Image.Image]] = {}
_RESIZED: dict[tuple[str, int, int, int], Image.Image] = {}
_MAX_CACHED = 8


def _overlay_source(path: str) -> Image.Image | None:
    """La imagen pegada (RGBA) o None si no existe o no se puede abrir. Se guarda en memoria mientras el archivo no
    cambie: mover o redimensionar una imagen repinta muchas veces por segundo."""
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return None
    cached = _SOURCES.get(path)
    if cached is not None and cached[:2] == (stat.st_mtime_ns, stat.st_size):
        return cached[2]
    try:
        img = load_image(p)
    except AnnotateError:
        return None
    if len(_SOURCES) >= _MAX_CACHED:
        _SOURCES.pop(next(iter(_SOURCES)))
    _SOURCES[path] = (stat.st_mtime_ns, stat.st_size, img)
    return img


def _overlay_picture(path: str, source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """La imagen a `size`, remuestreada con LANCZOS SIEMPRE desde el original (a su tamano real no se toca)."""
    if source.size == size:
        return source
    mtime = Path(path).stat().st_mtime_ns
    key = (path, mtime, size[0], size[1])
    picture = _RESIZED.get(key)
    if picture is None:
        picture = source.resize(size, Image.LANCZOS)
        if len(_RESIZED) >= _MAX_CACHED:
            _RESIZED.pop(next(iter(_RESIZED)))
        _RESIZED[key] = picture
    return picture


def missing_overlays(items: Sequence[Annotation]) -> list[str]:
    """Rutas de las imagenes pegadas que ya no se pueden abrir (se borro o movio el archivo)."""
    return [i.path for i in items if isinstance(i, ImageOverlay) and _overlay_source(i.path) is None]


def _rounded_mask(size: tuple[int, int], radius: float) -> Image.Image:
    """Mascara 'L' de un rectangulo de `size` con esquinas redondeadas (a 4x para que el borde salga suave)."""
    w, h = size
    radius = min(radius, w / 2, h / 2)
    if radius < 0.5:
        return Image.new("L", size, 255)
    big = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 4, fill=255)
    return big.resize(size, Image.LANCZOS)


def _alpha_paste(out: Image.Image, layer: Image.Image, x: int, y: int) -> None:
    """Compone `layer` (RGBA) sobre `out` en (x, y), recortando lo que se sale de `out`."""
    left, top = max(0, x), max(0, y)
    right, bottom = min(out.width, x + layer.width), min(out.height, y + layer.height)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (x, y, x + layer.width, y + layer.height):
        layer = layer.crop((left - x, top - y, right - x, bottom - y))
    out.alpha_composite(layer, (left, top))


def _shadow_layer(size: tuple[int, int], mask: Image.Image, opacity: float, strength: float, scale: float):
    """(capa RGBA de la sombra, margen): negro con el contorno de la imagen, desplazado hacia abajo y desenfocado."""
    sigma = style.OVERLAY_SHADOW_BLUR * scale
    dy = round(style.OVERLAY_SHADOW_DY * scale)
    margin = int(3 * sigma) + abs(dy) + 2
    alpha = Image.new("L", (size[0] + 2 * margin, size[1] + 2 * margin), 0)
    alpha.paste(mask, (margin, margin + dy))
    alpha = alpha.filter(ImageFilter.GaussianBlur(sigma))
    factor = min(1.0, style.OVERLAY_SHADOW_ALPHA * strength) * opacity
    alpha = alpha.point(lambda v: round(v * factor))
    layer = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    layer.putalpha(alpha)
    return layer, margin


def apply_overlays(img: Image.Image, items: Sequence[Annotation], scale: float = 1.0) -> Image.Image:
    """Copia de `img` con cada ImageOverlay compuesta (en el orden de la lista: la ultima queda encima). Sin imagenes
    pegadas devuelve la misma. Lo que se sale de la captura se recorta; un archivo que ya no existe se omite (usa
    `missing_overlays` para avisarlo)."""
    overlays = [i for i in items if isinstance(i, ImageOverlay)]
    if not overlays:
        return img
    out = img.copy()
    for ov in overlays:
        source = _overlay_source(ov.path)
        if source is None:
            continue
        x0, y0 = int(round(ov.rect.x)), int(round(ov.rect.y))
        size = (max(1, int(round(ov.rect.w))), max(1, int(round(ov.rect.h))))
        picture = _overlay_picture(ov.path, source, size)
        mask = _rounded_mask(size, ov.corner)
        if ov.shadow:
            layer, margin = _shadow_layer(size, mask, ov.opacity, ov.shadow_strength, scale)
            _alpha_paste(out, layer, x0 - margin, y0 - margin)
        alpha = ImageChops.multiply(picture.getchannel("A"), mask)
        if ov.opacity < 1.0:
            alpha = alpha.point(lambda v, f=ov.opacity: round(v * f))
        layer = picture.copy()
        layer.putalpha(alpha)
        _alpha_paste(out, layer, x0, y0)
        if ov.border:
            edge = Image.new("RGBA", size, (0, 0, 0, 0))
            width = max(1, round(1.2 * scale))
            ImageDraw.Draw(edge).rounded_rectangle(
                (0, 0, size[0] - 1, size[1] - 1), radius=min(ov.corner, size[0] / 2, size[1] / 2),
                outline=(0, 0, 0, round(style.OVERLAY_BORDER_ALPHA * ov.opacity)), width=width,
            )
            _alpha_paste(out, edge, x0, y0)
    return out


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
