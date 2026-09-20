"""Escalar una captura (p. ej. de Lightshot) a 2x, 3x o 4x con Pillow: remuestreo LANCZOS y un poco de nitidez.
Es una fase sin IA: agranda de forma limpia (el texto se ve suave en vez de pixelado al ampliar) pero NO inventa
detalle que la captura no tiene. La captura original no se toca: el resultado se guarda aparte (`nombre@2x.png`)."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageFilter

from core.annotate.errors import AnnotateError
from core.annotate.raster import load_image

FACTORS = (2, 3, 4)
MAX_OUTPUT_PIXELS = 100_000_000   # ~400 MB en RGBA: mas que eso es casi seguro un error (o se queda sin memoria)
SHARPEN_PERCENT = 70
SHARPEN_THRESHOLD = 1             # no realza el ruido de las zonas casi planas


def scaled_size(size: tuple[int, int], factor: int) -> tuple[int, int]:
    return size[0] * factor, size[1] * factor


def scaled_output_path(image_path: Path, factor: int) -> Path:
    """<nombre>@2x.png junto a la captura (siempre PNG, sin perdida)."""
    return image_path.with_name(f"{image_path.stem}@{factor}x.png")


def _check_factor(factor: int) -> None:
    if factor not in FACTORS:
        raise AnnotateError(f"Escala no valida: {factor}x (usa {', '.join(f'{f}x' for f in FACTORS)}).")


def upscale(img: Image.Image, factor: int, sharpen: bool = True) -> Image.Image:
    """Copia de `img` agrandada `factor` veces. La nitidez (unsharp mask, con radio proporcional a la escala) solo
    toca el color: el canal alfa se conserva tal cual para no dejar halos en los bordes transparentes."""
    _check_factor(factor)
    width, height = scaled_size(img.size, factor)
    if width * height > MAX_OUTPUT_PIXELS:
        raise AnnotateError(
            f"El resultado seria de {width} x {height} px ({width * height / 1e6:.0f} MP): demasiado grande. "
            f"Prueba una escala menor."
        )
    big = img.convert("RGBA").resize((width, height), Image.LANCZOS)
    if not sharpen:
        return big
    r, g, b, a = big.split()
    color = Image.merge("RGB", (r, g, b)).filter(
        ImageFilter.UnsharpMask(radius=0.5 * factor + 0.3, percent=SHARPEN_PERCENT, threshold=SHARPEN_THRESHOLD)
    )
    return Image.merge("RGBA", (*color.split(), a))


def save_upscaled(source: Path, output: Path, factor: int, sharpen: bool = True) -> tuple[int, int]:
    """Carga `source` (respeta EXIF), la escala y la guarda como PNG en `output`. Devuelve el tamano resultante.
    Nunca sobrescribe la captura original. Se escribe a un temporal y se renombra: un fallo no deja un PNG a medias."""
    if output.resolve() == source.resolve():
        raise AnnotateError("La ruta de salida es la captura original. Elige otro nombre.")
    if output.suffix.lower() != ".png":
        raise AnnotateError("La captura escalada se guarda como PNG.")
    out = upscale(load_image(source), factor, sharpen)
    if out.getchannel("A").getextrema() == (255, 255):
        out = out.convert("RGB")   # sin transparencia: el PNG pesa bastante menos
    tmp = output.with_name(f"{output.name}.tmp")
    try:
        out.save(tmp, format="PNG")
        os.replace(tmp, output)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise AnnotateError(f"No se pudo guardar {output.name}: {exc}") from exc
    return out.size
