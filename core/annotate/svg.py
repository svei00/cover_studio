"""Primitivas a SVG y exportacion. El bitmap que se incrusta es siempre el ya
pixelado, nunca el original."""

from __future__ import annotations

import base64
import io
from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image

from core.annotate import style
from core.annotate.errors import AnnotateError
from core.annotate.model import AnnotationDoc
from core.annotate.primitives import (
    PCircle,
    PEllipse,
    PImage,
    PLine,
    PPolygon,
    PRect,
    PText,
    Primitive,
    build_primitives,
)
from core.annotate.raster import apply_redactions, lens_crops, load_image
from core.geometry import escape_xml, render_png, render_png_bytes


def _f(value: float) -> str:
    return f"{value:.2f}"


def _dash(dash: tuple[float, float] | None) -> str:
    return f' stroke-dasharray="{_f(dash[0])} {_f(dash[1])}"' if dash else ""


def _image_to_svg(p: PImage, crops: Mapping[str, Image.Image] | None) -> str:
    """Imagen del lente recortada con su forma. Sin recorte disponible no dibuja nada."""
    if not crops or p.key not in crops:
        return ""
    clip_id = f"lens-{p.key}"
    d = p.dest
    if p.shape == "circle":
        shape = f'<circle cx="{_f(d.center[0])}" cy="{_f(d.center[1])}" r="{_f(d.w / 2)}"/>'
    elif p.shape == "ellipse":
        shape = (
            f'<ellipse cx="{_f(d.center[0])}" cy="{_f(d.center[1])}" '
            f'rx="{_f(d.w / 2)}" ry="{_f(d.h / 2)}"/>'
        )
    else:
        shape = (
            f'<rect x="{_f(d.x)}" y="{_f(d.y)}" width="{_f(d.w)}" height="{_f(d.h)}" '
            f'rx="{_f(p.rx)}"/>'
        )
    return (
        f'<clipPath id="{clip_id}">{shape}</clipPath>'
        f'<image x="{_f(d.x)}" y="{_f(d.y)}" width="{_f(d.w)}" height="{_f(d.h)}" '
        f'preserveAspectRatio="none" clip-path="url(#{clip_id})" '
        f'xlink:href="{_png_data_uri(crops[p.key])}"/>'
    )


def primitive_to_svg(p: Primitive, crops: Mapping[str, Image.Image] | None = None) -> str:
    if isinstance(p, PImage):
        return _image_to_svg(p, crops)
    if isinstance(p, PRect):
        fill = f'fill="{p.fill}" fill-opacity="{p.fill_opacity}"' if p.fill else 'fill="none"'
        stroke = (
            f'stroke="{p.stroke}" stroke-width="{_f(p.width)}" stroke-opacity="{p.opacity}"'
            f'{_dash(p.dash)}'
            if p.stroke
            else ""
        )
        blend = f' style="mix-blend-mode:{p.blend}"' if p.blend else ""
        return (
            f'<rect x="{_f(p.rect.x)}" y="{_f(p.rect.y)}" width="{_f(p.rect.w)}" '
            f'height="{_f(p.rect.h)}" rx="{_f(p.rx)}" {fill} {stroke}{blend}/>'
        )
    if isinstance(p, PLine):
        return (
            f'<line x1="{_f(p.a[0])}" y1="{_f(p.a[1])}" x2="{_f(p.b[0])}" y2="{_f(p.b[1])}" '
            f'stroke="{p.stroke}" stroke-width="{_f(p.width)}" stroke-opacity="{p.opacity}"/>'
        )
    if isinstance(p, PPolygon):
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in p.points)
        fill = f'fill="{p.fill}"' if p.fill else 'fill="none"'
        stroke = (
            f'stroke="{p.stroke}" stroke-width="{_f(p.width)}" stroke-opacity="{p.opacity}" '
            f'stroke-linejoin="round"'
            if p.stroke
            else ""
        )
        return f'<polygon points="{pts}" {fill} {stroke}/>'
    if isinstance(p, PEllipse):
        fill = f'fill="{p.fill}"' if p.fill else 'fill="none"'
        stroke = (
            f'stroke="{p.stroke}" stroke-width="{_f(p.width)}" stroke-opacity="{p.opacity}"{_dash(p.dash)}'
            if p.stroke
            else ""
        )
        return (
            f'<ellipse cx="{_f(p.center[0])}" cy="{_f(p.center[1])}" rx="{_f(p.rx)}" '
            f'ry="{_f(p.ry)}" {fill} {stroke}/>'
        )
    if isinstance(p, PCircle):
        fill = f'fill="{p.fill}"' if p.fill else 'fill="none"'
        stroke = (
            f'stroke="{p.stroke}" stroke-width="{_f(p.width)}" stroke-opacity="{p.opacity}"{_dash(p.dash)}'
            if p.stroke
            else ""
        )
        return f'<circle cx="{_f(p.center[0])}" cy="{_f(p.center[1])}" r="{_f(p.r)}" {fill} {stroke}/>'
    if isinstance(p, PText):
        outline = (
            f' stroke="{p.outline}" stroke-width="{_f(p.outline_width)}" '
            f'stroke-linejoin="round" paint-order="stroke fill"'
            if p.outline
            else ""
        )
        return (
            f'<text x="{_f(p.pos[0])}" y="{_f(p.pos[1])}" text-anchor="{p.anchor}" '
            f'dominant-baseline="central" font-family="{escape_xml(style.FONT)}" '
            f'font-size="{_f(p.size)}" font-weight="{"700" if p.bold else "400"}" '
            f'fill="{p.color}"{outline}>{escape_xml(p.text)}</text>'
        )
    raise TypeError(f"Primitiva desconocida: {type(p).__name__}")


def _png_data_uri(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def canvas_size(doc: AnnotationDoc) -> tuple[int, int]:
    view = doc.view
    return int(view.w) + 2 * doc.padding, int(view.h) + 2 * doc.padding


def to_svg(
    doc: AnnotationDoc,
    base: Image.Image,
    primitives: Sequence[Primitive],
    crops: Mapping[str, Image.Image] | None = None,
) -> str:
    """SVG completo: relleno (si hay padding), bitmap ya pixelado y anotaciones.
    crops son los recortes de las lupas (raster.lens_crops)."""
    width, height = canvas_size(doc)
    pad = doc.padding
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    ]
    if pad:
        parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{style.CARD_FILL}"/>')
    view = doc.view
    # las anotaciones siguen en coordenadas de la fuente: se traslada por -recorte
    parts.append(f'<g transform="translate({pad - int(view.x)} {pad - int(view.y)})">')
    if doc.crop is not None:
        # solo viaja el bitmap recortado: los pixeles de fuera no quedan en el SVG
        box = (int(view.x), int(view.y), int(view.right), int(view.bottom))
        base = base.crop(box)
    parts.append(
        f'<image x="{int(view.x)}" y="{int(view.y)}" width="{int(view.w)}" height="{int(view.h)}" '
        f'xlink:href="{_png_data_uri(base)}"/>'
    )
    parts.extend(primitive_to_svg(p, crops) for p in primitives)
    parts.append("</g></svg>")
    return "\n".join(parts)


def default_output_path(image_path: Path) -> Path:
    """<nombre>-anotada.png junto a la captura."""
    return image_path.with_name(f"{image_path.stem}-anotada.png")


def build_svg(doc: AnnotationDoc) -> str:
    """Carga, pixela, genera primitivas y arma el SVG del documento."""
    image = load_image(doc.image_path)
    if image.size != tuple(doc.image_size):
        raise AnnotateError(
            f"La captura cambio de tamano ({image.size[0]}x{image.size[1]}, el proyecto "
            f"esperaba {doc.image_size[0]}x{doc.image_size[1]}). Reabre la captura."
        )
    redacted = apply_redactions(image, doc.items)
    return to_svg(doc, redacted, build_primitives(doc), lens_crops(redacted, doc.items))


def _check_not_original(doc: AnnotationDoc, output_path: Path, allow_overwrite: bool) -> None:
    if not allow_overwrite and output_path.resolve() == doc.image_path.resolve():
        raise AnnotateError(
            "La ruta de salida es la captura original. Elige otra ruta o confirma la sobrescritura."
        )


def render_bytes(doc: AnnotationDoc) -> bytes:
    """PNG de la captura anotada en memoria (para el portapapeles), sin tocar disco."""
    width, height = canvas_size(doc)
    return render_png_bytes(build_svg(doc), width, height)


def export_png(doc: AnnotationDoc, output_path: Path, allow_overwrite: bool = False) -> None:
    """Exporta la captura anotada como PNG a su tamano original (mas padding)."""
    _check_not_original(doc, output_path, allow_overwrite)
    width, height = canvas_size(doc)
    render_png(build_svg(doc), output_path, width, height)


def export_svg(doc: AnnotationDoc, output_path: Path, allow_overwrite: bool = False) -> None:
    """Exporta el SVG (con el bitmap ya pixelado incrustado)."""
    _check_not_original(doc, output_path, allow_overwrite)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(build_svg(doc), encoding="utf-8")
    except OSError as exc:
        raise AnnotateError(f"No se pudo escribir el SVG en {output_path}: {exc}") from exc
