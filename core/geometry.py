"""Construccion del SVG de la portada: banda, acento en L, titulo y subtitulo. Logica
pura, sin Qt, para poder testear y reusar desde CLI o UI."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import resvg_py
from PIL import Image, UnidentifiedImageError

from core.text_utils import MeasureFn, wrap_title

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


class SubtitlePosition(str, Enum):
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"


class GradientDirection(str, Enum):
    HORIZONTAL = "horizontal"   # del color 1 (izquierda) al color 2 (derecha)
    VERTICAL = "vertical"       # del color 1 (arriba) al color 2 (abajo)
    DIAGONAL = "diagonal"       # de la esquina superior izquierda a la inferior derecha


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
    auto_fit_font: bool = True
    max_lines: int = 2
    save_svg_alongside: bool = False
    # Subtitulo: una franja redondeada simple (sin capa doble ni sombra), opcional. Su texto no es parte
    # de la configuracion (como el titulo); si esta vacio no se dibuja nada.
    subtitle_position: SubtitlePosition = SubtitlePosition.BOTTOM_RIGHT
    subtitle_text_color: str = "#F1EBDF"
    subtitle_bg_color: str = "#1B3350"
    subtitle_bg_opacity: float = 0.90        # solo del relleno: el texto y el borde van al 100 %
    subtitle_border_color: str = "#2F80D6"
    subtitle_border_width: float = 2.0       # px; 0 = sin borde
    subtitle_font_size: float = 36.0
    # esquina superior izquierda elegida arrastrando el subtitulo en la vista previa (px del lienzo);
    # None = la que da `subtitle_position`. Van juntas.
    subtitle_x: float | None = None
    subtitle_y: float | None = None
    # Degradado de dos colores en el relleno de la franja: del `subtitle_bg_color` al `subtitle_bg_color2`
    # (por defecto, el azul de acento de la marca). La opacidad del fondo aplica a todo el degradado.
    subtitle_gradient: bool = False
    subtitle_bg_color2: str = "#3182DF"
    subtitle_gradient_direction: GradientDirection = GradientDirection.HORIZONTAL
    # Degradado de dos colores en el BORDE de la franja: del `subtitle_border_color` al `subtitle_border_color2`
    # (por defecto, el verde de la banda: azul -> verde, al reves del relleno para que el borde se distinga).
    # Usa la misma direccion que el degradado del relleno.
    subtitle_border_gradient: bool = False
    subtitle_border_color2: str = "#21B868"
    # Contorno de las letras, como el "Contorno del texto" del titulo (mismos colores y grosor automatico)
    subtitle_outline_enabled: bool = False
    subtitle_outline_color: str = "#B38E5D"


# Subtitulo: las medidas que dependen del lienzo se dan para un ancho de 1584 px y escalan con el ancho real.
SUBTITLE_REFERENCE_WIDTH = 1584.0
SUBTITLE_MARGIN = 24.0          # distancia de la franja al borde del lienzo, a 1584 px de ancho
SUBTITLE_PAD_X = 0.9            # relleno interno, en multiplos del tamano de letra
SUBTITLE_PAD_Y = 0.5
SUBTITLE_LINE_HEIGHT = 1.2
SUBTITLE_RADIUS = 0.4           # esquinas de la franja, en multiplos del tamano de letra
SUBTITLE_MAX_LINES = 2
SUBTITLE_MIN_FONT = 10.0
MAX_SUBTITLE_BORDER = 12.0


@dataclass(frozen=True)
class SubtitleLayout:
    """Subtitulo ya resuelto: lineas, tamano de letra y rectangulo (en px del lienzo) de la franja."""

    lines: tuple[str, ...]
    font_size: float
    rect: BandGeometry
    radius: float


def compute_subtitle_layout(config: CoverConfig, text: str, measure: MeasureFn) -> SubtitleLayout | None:
    """Franja del subtitulo, o None si el texto esta vacio. El texto se respeta tal como se escribio
    (no se normaliza ni se cambia a mayusculas). El ancho se ajusta al texto mas el relleno; si no cabe en
    el lienzo (menos los margenes) se parte en dos lineas y, si aun asi no cabe, se achica la letra. Nunca
    se sale del lienzo. `measure` es la misma MeasureFn que usa el titulo."""
    words = text.split()
    if not words:
        return None
    text = " ".join(words)
    canvas = config.canvas
    margin = SUBTITLE_MARGIN * canvas.width / SUBTITLE_REFERENCE_WIDTH
    initial = max(1.0, config.subtitle_font_size)
    max_width = max(1.0, canvas.width - 2 * margin - 2 * SUBTITLE_PAD_X * initial)

    result = wrap_title(
        text, measure, max_width, initial,
        max_lines=SUBTITLE_MAX_LINES, auto_fit=True, min_font_size=min(SUBTITLE_MIN_FONT, initial),
    )
    lines, font_size = result.lines, result.font_size

    # ultimo recurso (una palabra enorme que ni a la letra minima cabe): se achica proporcionalmente
    for _ in range(4):
        pad_x = SUBTITLE_PAD_X * font_size
        room = max(1.0, canvas.width - 2 * margin - 2 * pad_x)
        widest = max(measure(line, font_size) for line in lines)
        if widest <= room:
            break
        font_size = max(1.0, font_size * room / widest * 0.995)

    pad_x, pad_y = SUBTITLE_PAD_X * font_size, SUBTITLE_PAD_Y * font_size
    width = max(measure(line, font_size) for line in lines) + 2 * pad_x
    height = len(lines) * SUBTITLE_LINE_HEIGHT * font_size + 2 * pad_y
    width = min(width, canvas.width - 2 * margin)
    if config.subtitle_x is not None and config.subtitle_y is not None:
        x, y = config.subtitle_x, config.subtitle_y          # puesto a mano
    else:
        if config.subtitle_position is SubtitlePosition.BOTTOM_LEFT:
            x = margin
        elif config.subtitle_position is SubtitlePosition.BOTTOM_CENTER:
            x = (canvas.width - width) / 2
        else:
            x = canvas.width - margin - width
        y = canvas.height - margin - height
    x = min(max(0.0, x), max(0.0, canvas.width - width))   # nunca fuera del lienzo
    y = min(max(0.0, y), max(0.0, canvas.height - height))
    radius = min(height / 2, SUBTITLE_RADIUS * font_size)
    return SubtitleLayout(tuple(lines), font_size, BandGeometry(x, y, width, height), radius)


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
    subtitle: SubtitleLayout | None = None,
) -> str:
    """Ensambla el documento SVG completo: fondo (foto o marcador neutro),
    acento azul, banda verde, titulo y subtitulo (si hay), en ese orden de dibujo."""
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

    if subtitle is not None:
        svg.extend(_subtitle_svg(config, subtitle))

    svg.append('</svg>')
    return "\n".join(svg)


# vector (x1, y1, x2, y2) del degradado, en fracciones de la caja de la franja
_GRADIENT_VECTORS: dict[GradientDirection, tuple[int, int, int, int]] = {
    GradientDirection.HORIZONTAL: (0, 0, 1, 0),
    GradientDirection.VERTICAL: (0, 0, 0, 1),
    GradientDirection.DIAGONAL: (0, 0, 1, 1),
}


def _subtitle_svg(config: CoverConfig, subtitle: SubtitleLayout) -> list[str]:
    """Franja redondeada del subtitulo y su texto. UN solo rectangulo (sin capa doble ni sombra). La opacidad
    es solo del relleno; el borde y el texto se dibujan al 100 %. El borde se dibuja hacia adentro de la caja
    (el trazo es centrado), asi el tamano total y el margen al borde del lienzo no cambian con el grosor."""
    rect = subtitle.rect
    border = min(max(config.subtitle_border_width, 0.0), MAX_SUBTITLE_BORDER)
    opacity = min(max(config.subtitle_bg_opacity, 0.0), 1.0)
    inset = border / 2
    rx = max(0.0, subtitle.radius - inset)
    x1, y1, x2, y2 = _GRADIENT_VECTORS[config.subtitle_gradient_direction]
    gradients: list[str] = []

    def gradient(gradient_id: str, color1: str, color2: str) -> str:
        gradients.append(
            f'<linearGradient id="{gradient_id}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'
            f'<stop offset="0" stop-color="{color1}"/><stop offset="1" stop-color="{color2}"/></linearGradient>'
        )
        return f"url(#{gradient_id})"

    fill = config.subtitle_bg_color
    if config.subtitle_gradient:
        fill = gradient("subtitleGradient", config.subtitle_bg_color, config.subtitle_bg_color2)
    border_paint = config.subtitle_border_color
    if config.subtitle_border_gradient and border > 0:
        border_paint = gradient("subtitleBorderGradient", config.subtitle_border_color, config.subtitle_border_color2)
    stroke = f' stroke="{border_paint}" stroke-width="{border:.2f}"' if border > 0 else ""
    parts: list[str] = []
    if gradients:
        parts.append("<defs>" + "".join(gradients) + "</defs>")
    parts.append(
        f'<rect x="{rect.x + inset:.2f}" y="{rect.y + inset:.2f}" width="{rect.width - border:.2f}" '
        f'height="{rect.height - border:.2f}" rx="{rx:.2f}" fill="{fill}" '
        f'fill-opacity="{opacity:.2f}"{stroke}/>'
    )
    weight_css = _FONT_WEIGHT_CSS[config.font_weight]
    outline_attrs = ""
    if config.subtitle_outline_enabled:
        outline_width = max(2.0, subtitle.font_size * 0.02)   # la misma regla del contorno del titulo
        outline_attrs = (
            f' stroke="{config.subtitle_outline_color}" stroke-width="{outline_width:.2f}" '
            f'stroke-linejoin="round" paint-order="stroke fill"'
        )
    for line, x, y in layout_text_lines(subtitle.lines, rect, subtitle.font_size, SUBTITLE_LINE_HEIGHT):
        parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="{escape_xml(config.font_family)}" font-size="{subtitle.font_size:.2f}" '
            f'font-weight="{weight_css}" fill="{config.subtitle_text_color}"{outline_attrs}>{escape_xml(line)}</text>'
        )
    return parts


def render_png_bytes(svg_text: str, width: int, height: int) -> bytes:
    """Rasteriza el SVG a bytes PNG en memoria con resvg (sin dependencias
    nativas: a diferencia de cairosvg, no requiere libcairo instalado en el
    sistema, algo que en Windows normalmente obliga a instalar el runtime de
    GTK). Pensada para la vista previa, que no necesita tocar disco."""
    try:
        return resvg_py.svg_to_bytes(svg_string=svg_text, width=width, height=height)
    except ValueError as exc:
        raise GeometryError(f"No se pudo rasterizar el SVG: {exc}") from exc


def render_png(svg_text: str, output_path: Path, width: int, height: int) -> None:
    """Rasteriza el SVG y lo escribe como PNG en output_path."""
    png_bytes = render_png_bytes(svg_text, width, height)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(png_bytes)
    except OSError as exc:
        raise GeometryError(f"No se pudo escribir el PNG en {output_path}: {exc}") from exc
