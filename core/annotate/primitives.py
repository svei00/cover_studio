"""Del modelo de anotaciones a una lista de primitivas geometricas. La UI las
pinta con QPainter y el export las convierte a SVG: la geometria vive solo aqui.

marker_primitives es el port de Doc.marker() de infographic_builder.py."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from core.annotate import lens, style
from core.annotate.palette import BRAND_PALETTE, Palette
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowSide,
    Highlight,
    HighlightMode,
    LensShape,
    Magnifier,
    Marker,
    Rect,
    StepBadge,
    TextAlign,
    TextLabel,
)
from core.annotate.text_measure import measure_line

Point = tuple[float, float]


@dataclass(frozen=True)
class PRect:
    rect: Rect
    stroke: str | None
    width: float
    opacity: float = 1.0
    rx: float = 0.0
    fill: str | None = None
    fill_opacity: float = 1.0
    dash: tuple[float, float] | None = None
    blend: str | None = None   # 'multiply': se mezcla con lo de abajo (resaltador en modo Marcador)


@dataclass(frozen=True)
class PLine:
    a: Point
    b: Point
    stroke: str
    width: float
    opacity: float = 1.0


@dataclass(frozen=True)
class PPolygon:
    points: tuple[Point, ...]
    fill: str | None
    stroke: str | None
    width: float = 0.0
    opacity: float = 1.0


@dataclass(frozen=True)
class PCircle:
    center: Point
    r: float
    fill: str | None
    stroke: str | None
    width: float = 0.0
    dash: tuple[float, float] | None = None
    opacity: float = 1.0


@dataclass(frozen=True)
class PEllipse:
    center: Point
    rx: float
    ry: float
    fill: str | None
    stroke: str | None
    width: float = 0.0
    dash: tuple[float, float] | None = None
    opacity: float = 1.0


@dataclass(frozen=True)
class PImage:
    """Imagen recortada de un lente. key es el id del Magnifier; el recorte lo
    aporta quien dibuja (raster.lens_crops). shape: 'circle' o 'rounded'."""

    key: str
    dest: Rect
    shape: str
    rx: float = 0.0


@dataclass(frozen=True)
class PText:
    """pos es el centro vertical de la linea (para dominant-baseline central);
    anchor es 'start' o 'middle'."""

    pos: Point
    text: str
    size: float
    color: str
    bold: bool
    anchor: str = "middle"
    outline: str | None = None
    outline_width: float = 0.0


Primitive = PRect | PLine | PPolygon | PCircle | PEllipse | PText | PImage


# --------------------------------------------------------------------------
# Flechas
# --------------------------------------------------------------------------

def _arrow_parts(
    a: Point, b: Point, scale: float, glow: bool, color: str = style.RED, glow_color: str = style.GLOW_GOLD
) -> list[Primitive]:
    """Linea de a hacia b con punta en b, con el resplandor debajo."""
    x1, y1 = a
    x2, y2 = b
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return []
    sw = style.MARKER_STROKE * scale
    head = style.ARROW_HEAD * scale
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    bx, by = x2 - ux * head * 1.3, y2 - uy * head * 1.3
    px, py = -uy, ux
    pts = (
        (x2, y2),
        (bx + px * head * 0.8, by + py * head * 0.8),
        (bx - px * head * 0.8, by - py * head * 0.8),
    )
    parts: list[Primitive] = []
    if glow:
        parts.append(PLine(a, b, glow_color, sw + style.ARROW_GLOW_EXTRA * scale, style.ARROW_GLOW_OPACITY))
    parts.append(PLine(a, b, color, sw))
    if glow:
        parts.append(PPolygon(pts, None, glow_color, style.ARROW_GLOW_EXTRA * scale, style.ARROW_GLOW_OPACITY))
    parts.append(PPolygon(pts, color, None))
    return parts


def _marker_arrow_points(rect: Rect, side: ArrowSide, scale: float) -> tuple[Point, Point]:
    """(inicio, punta) de la flecha de un marcador del lado indicado."""
    gap = style.ARROW_GAP * scale
    alen = style.ARROW_LENGTH * scale
    cx, cy = rect.center
    if side is ArrowSide.LEFT:
        tip = (rect.x - gap, cy)
        return (tip[0] - alen, cy), tip
    if side is ArrowSide.RIGHT:
        tip = (rect.right + gap, cy)
        return (tip[0] + alen, cy), tip
    if side is ArrowSide.TOP:
        tip = (cx, rect.y - gap)
        return (cx, tip[1] - alen), tip
    if side is ArrowSide.BOTTOM:
        tip = (cx, rect.bottom + gap)
        return (cx, tip[1] + alen), tip
    raise ValueError(f"Lado de flecha no resuelto: {side}")


def _arrow_box(rect: Rect, side: ArrowSide, scale: float) -> Rect:
    start, tip = _marker_arrow_points(rect, side, scale)
    x0, x1 = sorted((start[0], tip[0]))
    y0, y1 = sorted((start[1], tip[1]))
    return Rect(x0, y0, x1 - x0, y1 - y0).inflate(style.ARROW_HEAD * scale)


# --------------------------------------------------------------------------
# Etiquetas de texto
# --------------------------------------------------------------------------

def label_box(t: TextLabel, scale: float) -> Rect:
    """Caja que ocupa una etiqueta, con su padding."""
    size = t.size * scale
    pad = t.padding * scale
    line_h = size * style.TEXT_LINE_HEIGHT
    lines = t.text.split("\n")
    width = max(measure_line(line, size, t.bold) for line in lines) + 2 * pad
    height = len(lines) * line_h + 2 * pad
    return Rect(t.pos[0], t.pos[1], width, height)


def text_label_primitives(t: TextLabel, scale: float) -> list[Primitive]:
    box = label_box(t, scale)
    size = t.size * scale
    pad = t.padding * scale
    line_h = size * style.TEXT_LINE_HEIGHT
    out: list[Primitive] = []
    if t.bg is not None or t.border is not None:
        out.append(
            PRect(
                box,
                stroke=t.border,
                width=t.border_width * scale if t.border else 0.0,
                rx=t.rx * scale,
                fill=t.bg,
                fill_opacity=t.bg_opacity,
            )
        )
    outline_w = max(2.0, size * 0.12) if t.outline else 0.0
    for i, line in enumerate(t.text.split("\n")):
        if not line:
            continue
        cy = box.y + pad + line_h * (i + 0.5)
        if t.align is TextAlign.CENTER:
            pos, anchor = (box.x + box.w / 2, cy), "middle"
        else:
            pos, anchor = (box.x + pad, cy), "start"
        out.append(PText(pos, line, size, t.color, t.bold, anchor, t.outline, outline_w))
    return out


# --------------------------------------------------------------------------
# Otras anotaciones
# --------------------------------------------------------------------------

def marker_primitives(
    m: Marker, scale: float, side: ArrowSide, palette: Palette = BRAND_PALETTE
) -> list[Primitive]:
    """Resplandor + recuadro + flecha, como Doc.marker(). Cada color es el propio del
    marcador o, si no tiene, el de la paleta (por defecto, los de marca)."""
    stroke = m.stroke_color or palette.marker
    glow_color = m.glow_color or palette.glow
    arrow_color = m.arrow_color or palette.arrow
    rx = style.MARKER_RX * scale
    out: list[Primitive] = []
    if m.glow:
        for off, op in style.GLOW_RINGS:
            o = off * scale
            out.append(PRect(m.rect.inflate(o), glow_color, style.GLOW_RING_WIDTH * scale, op, rx + o))
    out.append(PRect(m.rect, stroke, style.MARKER_STROKE * scale, 1.0, rx))
    if side is not ArrowSide.NONE:
        start, tip = _marker_arrow_points(m.rect, side, scale)
        out.extend(_arrow_parts(start, tip, scale, m.glow, arrow_color, glow_color))
    return out


def arrow_primitives(a: Arrow, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    return _arrow_parts(a.start, a.end, scale, a.glow, a.color or palette.arrow, a.glow_color or palette.glow)


def step_primitives(s: StepBadge, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    color = s.color or palette.step
    return [
        PCircle(s.center, style.STEP_RADIUS * scale, style.CARD_FILL, color, style.STEP_STROKE * scale),
        PText(s.center, str(s.number), style.STEP_FONT_SIZE * scale, color, True, "middle"),
    ]


def highlight_primitives(h: Highlight, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    blend = "multiply" if h.mode is HighlightMode.MARKER else None
    return [
        PRect(h.rect, None, 0.0, rx=h.radius * scale, fill=h.color or palette.highlight,
              fill_opacity=h.opacity, blend=blend)
    ]


def magnifier_primitives(m: Magnifier, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    """Contorno punteado del origen, conector, imagen del lente y su marco. Cada trazo de
    color lleva debajo uno navy mas ancho para que se lea sobre capturas claras."""
    src = lens.effective_source(m)
    box = lens.lens_rect(m)
    frame = m.frame_color or palette.lens
    dash = (6 * scale, 4 * scale)
    fw = m.frame_width                 # marco del lente (4 por defecto)
    thin = fw / 2                      # origen punteado y conector (2 por defecto)
    out: list[Primitive] = []
    rx = lens.lens_corner_radius(m) if m.shape is LensShape.ROUNDED else 0.0

    if m.glow:
        # debajo de todo: el conector y el origen se dibujan encima, y la imagen del lente
        # tapa la parte de los anillos que cae dentro
        glow_color = m.glow_color or palette.glow
        for off, op in style.GLOW_RINGS:
            o = (off + (fw - style.MARKER_STROKE) / 2) * scale
            width = style.GLOW_RING_WIDTH * scale
            if m.shape is LensShape.CIRCLE:
                out.append(PCircle(box.center, box.w / 2 + o, None, glow_color, width, opacity=op))
            elif m.shape is LensShape.ELLIPSE:
                out.append(PEllipse(box.center, box.w / 2 + o, box.h / 2 + o, None, glow_color, width, opacity=op))
            else:
                out.append(PRect(box.inflate(o), glow_color, width, op, rx + o))

    if m.shape is LensShape.CIRCLE:
        out.append(PCircle(src.center, src.w / 2, None, style.CARD_FILL, (thin + 2) * scale, opacity=0.6))
        out.append(PCircle(src.center, src.w / 2, None, frame, thin * scale, dash=dash))
    elif m.shape is LensShape.ELLIPSE:
        out.append(PEllipse(src.center, src.w / 2, src.h / 2, None, style.CARD_FILL, (thin + 2) * scale, opacity=0.6))
        out.append(PEllipse(src.center, src.w / 2, src.h / 2, None, frame, thin * scale, dash=dash))
    else:
        out.append(PRect(src, style.CARD_FILL, (thin + 2) * scale, 0.6, 3 * scale))
        out.append(PRect(src, frame, thin * scale, 1.0, 3 * scale, dash=dash))

    for a, b in lens.connector_segments(m):
        out.append(PLine(a, b, style.CARD_FILL, (thin + 2) * scale, 0.6))
        out.append(PLine(a, b, frame, thin * scale))

    out.append(PImage(m.id, box, m.shape.value, rx))
    if m.shape is LensShape.CIRCLE:
        out.append(PCircle(box.center, box.w / 2, None, style.CARD_FILL, (fw + 4) * scale))
        out.append(PCircle(box.center, box.w / 2, None, frame, fw * scale))
    elif m.shape is LensShape.ELLIPSE:
        out.append(PEllipse(box.center, box.w / 2, box.h / 2, None, style.CARD_FILL, (fw + 4) * scale))
        out.append(PEllipse(box.center, box.w / 2, box.h / 2, None, frame, fw * scale))
    else:
        out.append(PRect(box, style.CARD_FILL, (fw + 4) * scale, 1.0, rx))
        out.append(PRect(box, frame, fw * scale, 1.0, rx))
    return out


# --------------------------------------------------------------------------
# Limites y orquestacion
# --------------------------------------------------------------------------

def item_bounds(item: Annotation, scale: float) -> Rect | None:
    """Caja aproximada de una anotacion, para evitar que las flechas se pisen."""
    if isinstance(item, Marker):
        return item.rect.inflate(style.GLOW_RINGS[-1][0] * scale)
    if isinstance(item, Arrow):
        x0, x1 = sorted((item.start[0], item.end[0]))
        y0, y1 = sorted((item.start[1], item.end[1]))
        return Rect(x0, y0, x1 - x0, y1 - y0).inflate(style.ARROW_HEAD * scale)
    if isinstance(item, StepBadge):
        r = style.STEP_RADIUS * scale
        return Rect(item.center[0] - r, item.center[1] - r, 2 * r, 2 * r)
    if isinstance(item, TextLabel):
        return label_box(item, scale)
    if isinstance(item, Magnifier):
        return lens.lens_rect(item)
    return None


def resolve_arrow_side(
    marker: Marker,
    image_size: tuple[int, int],
    others: Sequence[Annotation],
    scale: float,
    region: Rect | None = None,
) -> ArrowSide:
    """AUTO elige el lado con mas espacio libre dentro de la imagen (o de `region`, la
    parte visible si hay recorte) y cuya flecha no pase sobre otras anotaciones; si
    ninguno cumple, el de mas espacio."""
    if marker.arrow is not ArrowSide.AUTO:
        return marker.arrow
    area = region or Rect(0.0, 0.0, float(image_size[0]), float(image_size[1]))
    r = marker.rect
    needed = (style.ARROW_GAP + style.ARROW_LENGTH + style.ARROW_HEAD) * scale
    free = {
        ArrowSide.LEFT: r.x - area.x,
        ArrowSide.RIGHT: area.right - r.right,
        ArrowSide.TOP: r.y - area.y,
        ArrowSide.BOTTOM: area.bottom - r.bottom,
    }
    order = sorted(free, key=lambda s: -free[s])
    obstacles = [b for o in others if o is not marker and (b := item_bounds(o, scale)) is not None]
    for side in order:
        if free[side] < needed:
            continue
        if not any(_arrow_box(r, side, scale).intersects(b) for b in obstacles):
            return side
    return order[0]


def doc_scale(doc: AnnotationDoc) -> float:
    """Escala de los trazos: la manual, o la automatica segun el ancho de lo que se
    exporta (el recorte, si lo hay)."""
    return doc.style_scale if doc.style_scale else style.auto_scale(doc.view.w)


def item_primitives(doc: AnnotationDoc, item: Annotation, scale: float) -> list[Primitive]:
    """Primitivas de una sola anotacion (las Redaction no generan: viven en el bitmap)."""
    if isinstance(item, Marker):
        side = resolve_arrow_side(item, doc.image_size, doc.items, scale, doc.view)
        return marker_primitives(item, scale, side, doc.palette)
    if isinstance(item, Arrow):
        return arrow_primitives(item, scale, doc.palette)
    if isinstance(item, StepBadge):
        return step_primitives(item, scale, doc.palette)
    if isinstance(item, TextLabel):
        return text_label_primitives(item, scale)
    if isinstance(item, Magnifier):
        return magnifier_primitives(item, scale, doc.palette)
    if isinstance(item, Highlight):
        return highlight_primitives(item, scale, doc.palette)
    return []


def build_primitives(doc: AnnotationDoc) -> list[Primitive]:
    """Primitivas de todo el documento, en orden de dibujo. Las Redaction no
    generan primitivas: viven en el bitmap."""
    scale = doc_scale(doc)
    out: list[Primitive] = []
    for item in doc.items:
        out.extend(item_primitives(doc, item, scale))
    return out
