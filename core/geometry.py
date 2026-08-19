"""Construccion del SVG de la portada: banda, acento en L y titulo. Logica
pura, sin Qt, para poder testear y reusar desde CLI o UI."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import resvg_py
from PIL import Image, UnidentifiedImageError

SUPPORTED_PHOTO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MIME_BY_SUFFIX = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


class GeometryError(Exception):
    """Error de geometria, de lectura de la foto o de escritura del resultado."""


class Orientation(str, Enum):
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM_LEFT = "bottom-left"
    TOP_RIGHT = "top-right"
    TOP_LEFT = "top-left"


class VerticalPosition(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class FontWeight(str, Enum):
    NORMAL = "normal"
    BOLD = "bold"


_FONT_WEIGHT_CSS = {FontWeight.NORMAL: "400", FontWeight.BOLD: "700"}

_ORIENTATION_SIGNS: dict[Orientation, tuple[int, int]] = {
    Orientation.BOTTOM_RIGHT: (1, 1),
    Orientation.BOTTOM_LEFT: (-1, 1),
    Orientation.TOP_RIGHT: (1, -1),
    Orientation.TOP_LEFT: (-1, -1),
}


@dataclass(frozen=True)
class CanvasSize:
    width: int
    height: int


@dataclass(frozen=True)
class BandGeometry:
    x: float
    y: float
    width: float
    height: float


@dataclass
class CoverConfig:
    canvas: CanvasSize = CanvasSize(1920, 1080)
    band_color: str = "#21B868"
    accent_color: str = "#3182DF"
    text_color: str = "#F1EBDF"
    text_outline_color: str = "#B38E5D"
    text_outline_enabled: bool = False
    band_opacity: float = 0.90
    accent_opacity_independent: bool = False
    accent_opacity: float = 0.90
    orientation: Orientation = Orientation.BOTTOM_RIGHT
    accent_shift: float = 30.0
    corner_radius: float = 0.0
    band_height: float = 210.0
    band_margin_left: float = 90.0
    band_margin_top: float = 80.0
    band_width: float | None = None
    vertical_position: VerticalPosition = VerticalPosition.TOP
    font_family: str = "Georgia, 'Times New Roman', serif"
    font_size: float = 78.0
    font_weight: FontWeight = FontWeight.BOLD
    text_shadow_enabled: bool = True
    text_shadow_intensity: float = 0.55
    inner_margin: float = 60.0


def compute_band_geometry(config: CoverConfig) -> BandGeometry:
    """Resuelve x, y, ancho y alto reales de la banda: ancho derivado
    (W - 2*margen_izq - 60) salvo que venga fijado, y posicion vertical
    top/center/bottom recalculando el margen superior efectivo."""
    width = config.band_width
    if width is None:
        width = config.canvas.width - 2 * config.band_margin_left - 60

    if config.vertical_position is VerticalPosition.TOP:
        y = config.band_margin_top
    elif config.vertical_position is VerticalPosition.CENTER:
        y = (config.canvas.height - config.band_height) / 2
    else:
        y = config.canvas.height - config.band_margin_top - config.band_height

    return BandGeometry(x=config.band_margin_left, y=y, width=width, height=config.band_height)


def _point_towards(a: tuple[float, float], b: tuple[float, float], dist: float) -> tuple[float, float]:
    """Punto sobre el segmento a->b a distancia `dist` de a, recortado a la mitad del segmento."""
    length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    if length == 0:
        return a
    t = min(dist, length / 2) / length
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _rounded_polygon_path(points: Sequence[tuple[float, float]], radius: float) -> str:
    """Path SVG cerrado que redondea cada vertice de un poligono (convexo o
    concavo) con curvas cuadraticas de radio `radius`, recortado por vertice
    a la mitad de sus dos lados adyacentes para no auto-intersectarse."""
    n = len(points)
    starts = []
    ends = []
    for i in range(n):
        prev_pt = points[(i - 1) % n]
        cur = points[i]
        nxt = points[(i + 1) % n]
        starts.append(_point_towards(cur, prev_pt, radius))
        ends.append(_point_towards(cur, nxt, radius))

    commands = [f"M {starts[0][0]:.2f} {starts[0][1]:.2f}"]
    for i in range(n):
        cur = points[i]
        commands.append(f"Q {cur[0]:.2f} {cur[1]:.2f} {ends[i][0]:.2f} {ends[i][1]:.2f}")
        next_start = starts[(i + 1) % n]
        commands.append(f"L {next_start[0]:.2f} {next_start[1]:.2f}")
    commands.append("Z")
    return " ".join(commands)


def compute_accent_path(
    band: BandGeometry,
    shift: float,
    corner_radius: float,
    orientation: Orientation,
) -> str:
    """Path SVG del acento en L: se deriva de un rectangulo del mismo
    tamano que la banda, desplazado `shift` px en diagonal hacia la esquina
    de la orientacion, al que se le resta la parte que cae dentro de la
    banda. Deja dos brazos de exactamente `shift` px de grosor unidos en esa
    esquina, sin traslape con la banda. Funciona para las cuatro
    orientaciones a partir del mismo derivado, solo cambiando el signo del
    desplazamiento."""
    sx, sy = _ORIENTATION_SIGNS[orientation]
    left, top = band.x, band.y
    right, bottom = band.x + band.width, band.y + band.height

    ax = left + sx * shift
    ay = top + sy * shift
    a_right = ax + band.width
    a_bottom = ay + band.height

    band_edge_x = right if sx > 0 else left
    band_edge_y = bottom if sy > 0 else top
    accent_far_x = a_right if sx > 0 else ax
    accent_far_y = a_bottom if sy > 0 else ay
    accent_near_x = ax if sx > 0 else a_right
    accent_near_y = ay if sy > 0 else a_bottom

    points = [
        (accent_near_x, band_edge_y),
        (band_edge_x, band_edge_y),
        (band_edge_x, accent_near_y),
        (accent_far_x, accent_near_y),
        (accent_far_x, accent_far_y),
        (accent_near_x, accent_far_y),
    ]
    return _rounded_polygon_path(points, max(corner_radius, 0.0))


def escape_xml(text: str) -> str:
    """Escapa &, <, >, comillas dobles y simples para insertar texto seguro en SVG."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def encode_image_data_uri(photo_path: Path) -> str:
    """Lee la foto de disco, valida que sea una imagen soportada con Pillow
    y arma el data URI base64 para incrustarla en el SVG."""
    if not photo_path.exists():
        raise GeometryError(f"No se encontro la foto: {photo_path}")

    suffix = photo_path.suffix.lower()
    if suffix not in SUPPORTED_PHOTO_SUFFIXES:
        raise GeometryError(
            f"Formato no soportado ({suffix or 'sin extension'}). Usa png, jpg, jpeg o webp."
        )

    try:
        with Image.open(photo_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise GeometryError(f"El archivo no es una imagen valida: {photo_path.name}") from exc

    mime = _MIME_BY_SUFFIX[suffix]
    data = photo_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def layout_text_lines(
    lines: Sequence[str],
    band: BandGeometry,
    font_size: float,
    line_height_ratio: float = 1.2,
) -> list[tuple[str, float, float]]:
    """Calcula (linea, x, y_centro) para cada linea del titulo, centradas
    como bloque en la banda. y_centro esta pensado para usarse con
    dominant-baseline="central", asi que no depende de una aproximacion de
    baseline por tamano de fuente."""
    n = len(lines)
    line_height = font_size * line_height_ratio
    cx = band.x + band.width / 2
    cy = band.y + band.height / 2
    result = []
    for i, line in enumerate(lines):
        y = cy + (i - (n - 1) / 2) * line_height
        result.append((line, cx, y))
    return result


def _resolve_opacities(config: CoverConfig) -> tuple[float, float]:
    band_opacity = config.band_opacity
    accent_opacity = config.accent_opacity if config.accent_opacity_independent else config.band_opacity
    return band_opacity, accent_opacity


def build_svg(
    config: CoverConfig,
    lines: Sequence[str],
    font_size: float,
    photo_path: Path | None = None,
) -> str:
    """Ensambla el documento SVG completo: fondo (foto o marcador neutro),
    acento azul, banda verde y titulo, en ese orden de dibujo."""
    band = compute_band_geometry(config)
    band_opacity, accent_opacity = _resolve_opacities(config)
    canvas = config.canvas

    shadow_opacity = config.text_shadow_intensity if config.text_shadow_enabled else 0.0
    outline_attrs = ""
    if config.text_outline_enabled:
        outline_width = max(2.0, font_size * 0.02)
        outline_attrs = (
            f' stroke="{config.text_outline_color}" stroke-width="{outline_width:.2f}" '
            f'paint-order="stroke fill"'
        )

    svg = [
        f'<svg viewBox="0 0 {canvas.width} {canvas.height}" width="{canvas.width}" '
        f'height="{canvas.height}" xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink">',
        '<defs>',
        f'<filter id="titleShadow" x="-10%" y="-30%" width="120%" height="180%">'
        f'<feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#0A1520" '
        f'flood-opacity="{shadow_opacity:.2f}"/></filter>',
        '</defs>',
    ]

    if photo_path is not None:
        data_uri = encode_image_data_uri(photo_path)
        svg.append(
            f'<image x="0" y="0" width="{canvas.width}" height="{canvas.height}" '
            f'preserveAspectRatio="xMidYMid slice" xlink:href="{data_uri}"/>'
        )
    else:
        svg.append(f'<rect x="0" y="0" width="{canvas.width}" height="{canvas.height}" fill="#6E6E6E"/>')

    accent_path = compute_accent_path(band, config.accent_shift, config.corner_radius, config.orientation)
    svg.append(f'<path d="{accent_path}" fill="{config.accent_color}" fill-opacity="{accent_opacity}"/>')
    svg.append(
        f'<rect x="{band.x}" y="{band.y}" width="{band.width}" height="{band.height}" '
        f'rx="{config.corner_radius}" fill="{config.band_color}" fill-opacity="{band_opacity}"/>'
    )

    weight_css = _FONT_WEIGHT_CSS[config.font_weight]
    filter_attr = ' filter="url(#titleShadow)"' if config.text_shadow_enabled else ""
    for line, x, y in layout_text_lines(lines, band, font_size):
        svg.append(
            f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="{escape_xml(config.font_family)}" font-size="{font_size}" '
            f'font-weight="{weight_css}" fill="{config.text_color}"{outline_attrs}{filter_attr}>'
            f'{escape_xml(line)}</text>'
        )

    svg.append('</svg>')
    return "\n".join(svg)


def render_png(svg_text: str, output_path: Path, width: int, height: int) -> None:
    """Rasteriza el SVG a PNG con resvg (sin dependencias nativas: a
    diferencia de cairosvg, no requiere libcairo instalado en el sistema,
    algo que en Windows normalmente obliga a instalar el runtime de GTK)."""
    try:
        png_bytes = resvg_py.svg_to_bytes(svg_string=svg_text, width=width, height=height)
    except ValueError as exc:
        raise GeometryError(f"No se pudo rasterizar el SVG: {exc}") from exc

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(png_bytes)
    except OSError as exc:
        raise GeometryError(f"No se pudo escribir el PNG en {output_path}: {exc}") from exc
