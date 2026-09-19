"""Del modelo de anotaciones a una lista de primitivas geometricas. La UI las
pinta con QPainter y el export las convierte a SVG: la geometria vive solo aqui.

marker_primitives es el port de Doc.marker() de infographic_builder.py."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from core.annotate import freehand, lens, style
from core.annotate.palette import BRAND_PALETTE, Palette
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowSide,
    Highlight,
    HeadStyle,
    HighlightMode,
    LensShape,
    LineStyle,
    Magnifier,
    Marker,
    PenMode,
    Rect,
    StepBadge,
    StepShape,
    Stroke,
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
    dash: tuple[float, ...] | None = None
    blend: str | None = None   # 'multiply': se mezcla con lo de abajo (resaltador en modo Marcador)
    cap: str = "butt"          # 'round' para los puntos de una linea punteada


@dataclass(frozen=True)
class PLine:
    a: Point
    b: Point
    stroke: str
    width: float
    opacity: float = 1.0
    dash: tuple[float, ...] | None = None
    cap: str = "butt"


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
    dash: tuple[float, ...] | None = None
    opacity: float = 1.0
    cap: str = "butt"


@dataclass(frozen=True)
class PEllipse:
    center: Point
    rx: float
    ry: float
    fill: str | None
    stroke: str | None
    width: float = 0.0
    dash: tuple[float, ...] | None = None
    opacity: float = 1.0
    cap: str = "butt"


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
    opacity: float = 1.0


@dataclass(frozen=True)
class PPolyline:
    """Polilinea abierta de trazo redondo (el trazo a mano alzada). `blend` 'multiply' = resaltador."""

    points: tuple[Point, ...]
    stroke: str
    width: float
    opacity: float = 1.0
    blend: str | None = None


Primitive = PRect | PLine | PPolygon | PCircle | PEllipse | PText | PImage | PPolyline


# --------------------------------------------------------------------------
# Flechas
# --------------------------------------------------------------------------

def dash_pattern(line_style: LineStyle, width: float) -> tuple[tuple[float, ...] | None, str]:
    """(patron de rayas, tipo de remate) de un estilo de linea para un trazo de `width`. Las rayas se miden
    en multiplos del grosor, asi que se ven igual de proporcionadas con cualquier grosor; las de puntos y
    raya-punto llevan remate redondo (el punto es una raya casi nula con extremos redondos)."""
    w = width
    if line_style is LineStyle.DASHED:
        return (3 * w, 2 * w), "butt"
    if line_style is LineStyle.DOTTED:
        return (0.01 * w, 2 * w), "round"
    if line_style is LineStyle.DASH_DOT:
        return (2 * w, 2.5 * w, 0.01 * w, 2.5 * w), "round"
    return None, "butt"


def _head_points(tip: Point, ux: float, uy: float, head: float) -> tuple[Point, Point, Point]:
    """Triangulo de una punta de flecha con la punta en `tip`, mirando hacia (ux, uy)."""
    bx, by = tip[0] - ux * head * 1.3, tip[1] - uy * head * 1.3
    px, py = -uy, ux
    return (
        tip,
        (bx + px * head * 0.8, by + py * head * 0.8),
        (bx - px * head * 0.8, by - py * head * 0.8),
    )


def _line_parts(
    a: Point,
    b: Point,
    scale: float,
    glow: bool,
    color: str = style.RED,
    glow_color: str = style.GLOW_GOLD,
    width: float = style.MARKER_STROKE,
    head_start: HeadStyle = HeadStyle.NONE,
    head_end: HeadStyle = HeadStyle.ARROW,
    line_style: LineStyle = LineStyle.SOLID,
) -> list[Primitive]:
    """Linea de a hacia b con puntas opcionales en cada extremo, con el resplandor debajo."""
    x1, y1 = a
    x2, y2 = b
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return []
    sw = width * scale
    head = style.ARROW_HEAD * scale * min(3.0, max(0.5, width / style.MARKER_STROKE))   # la punta sigue al grosor
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    dash, cap = dash_pattern(line_style, sw)
    extra = style.ARROW_GLOW_EXTRA * scale
    heads = [(h, p, d) for h, p, d in ((head_end, b, (ux, uy)), (head_start, a, (-ux, -uy))) if h is not HeadStyle.NONE]
    parts: list[Primitive] = []
    if glow:
        parts.append(PLine(a, b, glow_color, sw + extra, style.ARROW_GLOW_OPACITY, dash, cap))
    parts.append(PLine(a, b, color, sw, 1.0, dash, cap))
    for kind, point, (dx, dy) in heads:
        if kind is HeadStyle.DOT:
            radius = max(sw * 1.2, head * 0.35)
            if glow:
                parts.append(PCircle(point, radius, None, glow_color, extra, opacity=style.ARROW_GLOW_OPACITY))
            parts.append(PCircle(point, radius, color, None))
        else:
            pts = _head_points(point, dx, dy, head)
            if glow:
                parts.append(PPolygon(pts, None, glow_color, extra, style.ARROW_GLOW_OPACITY))
            parts.append(PPolygon(pts, color, None))
    return parts


def _arrow_parts(
    a: Point, b: Point, scale: float, glow: bool, color: str = style.RED, glow_color: str = style.GLOW_GOLD
) -> list[Primitive]:
    """Linea de a hacia b con punta en b, con el resplandor debajo (la flecha de siempre)."""
    return _line_parts(a, b, scale, glow, color, glow_color)


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


def marker_arrow(m: Marker, doc: AnnotationDoc, scale: float) -> tuple[Point, Point] | None:
    """(inicio, punta) de la flecha del marcador tal como se dibuja, o None si no lleva."""
    side = resolve_arrow_side(m, doc.image_size, doc.items, scale, doc.view)
    if side is ArrowSide.NONE:
        return None
    if m.custom_arrow:
        return m.arrow_start, m.arrow_tip
    return _marker_arrow_points(m.rect, side, scale)


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
                opacity=t.opacity,
                rx=t.rx * scale,
                fill=t.bg,
                fill_opacity=t.bg_opacity * t.opacity,
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
        out.append(PText(pos, line, size, t.color, t.bold, anchor, t.outline, outline_w, t.opacity))
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
        if m.custom_arrow:
            start, tip = m.arrow_start, m.arrow_tip
        else:
            start, tip = _marker_arrow_points(m.rect, side, scale)
        out.extend(_arrow_parts(start, tip, scale, m.glow, arrow_color, glow_color))
    return out


def arrow_primitives(a: Arrow, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    return _line_parts(
        a.start, a.end, scale, a.glow, a.color or palette.arrow, a.glow_color or palette.glow,
        a.width, a.head_start, a.head_end, a.line_style,
    )


def step_extent(s: StepBadge, scale: float) -> float:
    """Semi-ancho del paso desde su centro (el rombo es mas ancho que el circulo del mismo radio)."""
    r = s.size * scale
    return r * style.STEP_DIAMOND_FACTOR if s.shape is StepShape.DIAMOND else r


def _diamond(center: Point, half: float) -> tuple[Point, Point, Point, Point]:
    cx, cy = center
    return (cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)


def step_primitives(s: StepBadge, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    border = s.color or palette.step
    fill = s.fill_color or style.CARD_FILL
    number_color = s.number_color or border
    r = s.size * scale
    sw = s.border_width * scale
    font = (s.number_size if s.number_size else s.size * style.STEP_NUMBER_RATIO) * scale
    cx, cy = s.center
    box = Rect(cx - r, cy - r, 2 * r, 2 * r)
    corner = r * style.STEP_ROUNDED_CORNER if s.shape is StepShape.ROUNDED else 0.0
    out: list[Primitive] = []
    if s.glow:
        glow_color = s.glow_color or palette.glow
        for off, op in style.GLOW_RINGS:
            o = max(0.0, off + (s.border_width - style.MARKER_STROKE) / 2) * scale
            width = style.GLOW_RING_WIDTH * scale
            if s.shape is StepShape.CIRCLE:
                out.append(PCircle(s.center, r + o, None, glow_color, width, opacity=op))
            elif s.shape is StepShape.DIAMOND:
                half = r * style.STEP_DIAMOND_FACTOR + o * math.sqrt(2)   # un rombo ensanchado `o` por cada lado
                out.append(PPolygon(_diamond(s.center, half), None, glow_color, width, op))
            else:
                out.append(PRect(box.inflate(o), glow_color, width, op, corner + o))
    if s.shape is StepShape.CIRCLE:
        out.append(PCircle(s.center, r, fill, border, sw))
    elif s.shape is StepShape.DIAMOND:
        out.append(PPolygon(_diamond(s.center, r * style.STEP_DIAMOND_FACTOR), fill, border, sw))
    else:
        out.append(PRect(box, border, sw, 1.0, corner, fill=fill))
    out.append(PText(s.center, str(s.number), font, number_color, True, "middle"))
    return out


def stroke_curve(s: Stroke) -> tuple[Point, ...]:
    """La polilinea que se dibuja de un trazo (curva por sus puntos de control). Un trazo de un solo punto
    es un punto: se dibuja como un segmento diminuto para que el remate redondo lo pinte."""
    curve = freehand.flatten(s.points)
    if len(curve) == 1:
        curve = [curve[0], (curve[0][0] + 0.01, curve[0][1])]
    return tuple(curve)


def stroke_primitives(s: Stroke, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    if not s.points:
        return []
    color = s.color or (palette.pen if s.mode is PenMode.PEN else palette.highlight)
    curve = stroke_curve(s)
    width = s.width * scale
    out: list[Primitive] = []
    if s.glow:
        # el mismo halo en capas que el conector de la lupa: de la mas ancha y tenue a la mas angosta
        glow_color = s.glow_color or palette.glow
        for off, op in reversed(style.GLOW_RINGS):
            out.append(PPolyline(curve, glow_color, width + 2 * off * scale, op * style.CONNECTOR_GLOW_STRENGTH))
    out.append(PPolyline(curve, color, width, s.opacity, "multiply" if s.mode is PenMode.MARKER else None))
    return out


def highlight_primitives(h: Highlight, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    blend = "multiply" if h.mode is HighlightMode.MARKER else None
    return [
        PRect(h.rect, None, 0.0, rx=h.radius * scale, fill=h.color or palette.highlight,
              fill_opacity=h.opacity, blend=blend)
    ]


def magnifier_primitives(m: Magnifier, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    """Contorno del origen, conector, imagen del lente y su marco. Cada trazo de color lleva
    debajo uno navy mas ancho (continuo) para que se lea sobre capturas claras. Marco, origen y
    conector tienen cada uno su color, grosor y estilo de linea."""
    src = lens.effective_source(m)
    box = lens.lens_rect(m)
    frame = m.frame_color or palette.lens
    fw = m.frame_width                 # marco del lente (4 por defecto)
    src_color = m.source_color or frame
    src_w = m.source_width if m.source_width is not None else fw / 2        # origen (2 por defecto)
    con_color = m.connector_color or frame
    con_w = m.connector_width if m.connector_width is not None else fw / 2  # conector (2 por defecto)
    src_dash, src_cap = dash_pattern(m.source_style, src_w * scale)
    con_dash, con_cap = dash_pattern(m.connector_style, con_w * scale)
    frame_dash, frame_cap = dash_pattern(m.frame_style, fw * scale)
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

    sw = (src_w + 2) * scale   # el contorno navy del origen
    if m.connector_glow:
        # halo del conector: lineas apiladas, de la mas ancha (y mas tenue) a la mas angosta, con el mismo alcance
        # y la misma progresion que los anillos del resplandor del lente; llevan las rayas del conector y van
        # debajo de su contorno navy y de su trazo de color
        glow_color = m.glow_color or palette.glow
        for a, b in lens.connector_segments(m):
            for off, op in reversed(style.GLOW_RINGS):
                out.append(PLine(
                    a, b, glow_color, con_w * scale + 2 * off * scale, op * style.CONNECTOR_GLOW_STRENGTH,
                    con_dash, con_cap,
                ))

    if m.shape is LensShape.CIRCLE:
        out.append(PCircle(src.center, src.w / 2, None, style.CARD_FILL, sw, opacity=0.6))
        out.append(PCircle(src.center, src.w / 2, None, src_color, src_w * scale, dash=src_dash, cap=src_cap))
    elif m.shape is LensShape.ELLIPSE:
        out.append(PEllipse(src.center, src.w / 2, src.h / 2, None, style.CARD_FILL, sw, opacity=0.6))
        out.append(PEllipse(src.center, src.w / 2, src.h / 2, None, src_color, src_w * scale, dash=src_dash, cap=src_cap))
    else:
        out.append(PRect(src, style.CARD_FILL, sw, 0.6, 3 * scale))
        out.append(PRect(src, src_color, src_w * scale, 1.0, 3 * scale, dash=src_dash, cap=src_cap))

    for a, b in lens.connector_segments(m):
        out.append(PLine(a, b, style.CARD_FILL, (con_w + 2) * scale, 0.6))
        out.append(PLine(a, b, con_color, con_w * scale, 1.0, con_dash, con_cap))

    out.append(PImage(m.id, box, m.shape.value, rx))
    if m.shape is LensShape.CIRCLE:
        out.append(PCircle(box.center, box.w / 2, None, style.CARD_FILL, (fw + 4) * scale))
        out.append(PCircle(box.center, box.w / 2, None, frame, fw * scale, dash=frame_dash, cap=frame_cap))
    elif m.shape is LensShape.ELLIPSE:
        out.append(PEllipse(box.center, box.w / 2, box.h / 2, None, style.CARD_FILL, (fw + 4) * scale))
        out.append(PEllipse(box.center, box.w / 2, box.h / 2, None, frame, fw * scale, dash=frame_dash, cap=frame_cap))
    else:
        out.append(PRect(box, style.CARD_FILL, (fw + 4) * scale, 1.0, rx))
        out.append(PRect(box, frame, fw * scale, 1.0, rx, dash=frame_dash, cap=frame_cap))
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
        r = step_extent(item, scale)
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
    """Escala de los trazos: la manual, o la automatica segun el ancho de la IMAGEN completa.
    Recortar no la cambia: el recorte es una ventana y las anotaciones se ven igual."""
    return doc.style_scale if doc.style_scale else style.auto_scale(doc.image_size[0])


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
    if isinstance(item, Stroke):
        return stroke_primitives(item, scale, doc.palette)
    return []


def build_primitives(doc: AnnotationDoc) -> list[Primitive]:
    """Primitivas de todo el documento, en orden de dibujo. Las Redaction no
    generan primitivas: viven en el bitmap."""
    scale = doc_scale(doc)
    out: list[Primitive] = []
    for item in doc.items:
        out.extend(item_primitives(doc, item, scale))
    return out
