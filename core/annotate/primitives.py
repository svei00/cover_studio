"""Del modelo de anotaciones a una lista de primitivas geometricas. La UI las
pinta con QPainter y el export las convierte a SVG: la geometria vive solo aqui.

marker_primitives es el port de Doc.marker() de infographic_builder.py."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from core.annotate import bracket as bracket_geometry
from core.annotate import freehand, icons, lens, style
from core.annotate.palette import BRAND_PALETTE, Palette
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowBody,
    ArrowSide,
    Bracket,
    BracketKind,
    ConnectorRoute,
    Highlight,
    HeadStyle,
    HighlightMode,
    Icon,
    IconStyle,
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
    TipContent,
    text_label_from_preset,
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
    """`opacity` es la del borde; `fill_opacity`, la del relleno (1 = opaco, como siempre)."""

    points: tuple[Point, ...]
    fill: str | None
    stroke: str | None
    width: float = 0.0
    opacity: float = 1.0
    fill_opacity: float = 1.0


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


@dataclass(frozen=True)
class PPath:
    """Camino abierto de esquinas en inglete (el conector en codo de la lupa): se pinta de un solo trazo, asi que ni la
    esquina ni las capas translucidas del resplandor se doblan donde se encuentran los tramos."""

    points: tuple[Point, ...]
    stroke: str
    width: float
    opacity: float = 1.0
    dash: tuple[float, ...] | None = None
    cap: str = "butt"


Primitive = PRect | PLine | PPolygon | PCircle | PEllipse | PText | PImage | PPolyline | PPath


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


def curve_control(start: Point, end: Point, bend: float) -> Point:
    """Punto de control de la curva (Bezier cuadratica) de una flecha: el centro del tramo desplazado `bend` veces su largo
    hacia un lado (el signo elige cual) en perpendicular."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    return ((start[0] + end[0]) / 2 - dy * bend, (start[1] + end[1]) / 2 + dx * bend)


def curve_apex(start: Point, end: Point, bend: float) -> Point:
    """El punto mas alejado de la curva respecto a la recta (su mitad): donde va el asa para doblarla."""
    cx, cy = curve_control(start, end, bend)
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    return (mx + (cx - mx) / 2, my + (cy - my) / 2)


def curve_points(start: Point, end: Point, bend: float) -> list[Point]:
    """La curva aplanada en puntos (mas o menos uno cada 5 px, entre 12 y 80 tramos): la usan el dibujo, la seleccion y las cotas."""
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    steps = min(80, max(12, int(length / 5)))
    cx, cy = curve_control(start, end, bend)
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u * u * start[0] + 2 * u * t * cx + t * t * end[0], u * u * start[1] + 2 * u * t * cy + t * t * end[1]))
    return out


def tapered_outline(route: Sequence[Point], width: float) -> tuple[Point, ...]:
    """Contorno (poligono) de un cuerpo CONICO sobre `route`: de `ARROW_TAIL_RATIO * width` en la cola a `width` en la punta,
    creciendo con lo recorrido. En las esquinas el desplazamiento sigue el inglete (acotado), asi un codo no se afina."""
    pts: list[Point] = []
    for p in route:
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) < 2:
        return ()
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    left: list[Point] = []
    right: list[Point] = []
    for i, (x, y) in enumerate(pts):
        half = width / 2 * (style.ARROW_TAIL_RATIO + (1 - style.ARROW_TAIL_RATIO) * cum[i] / total)
        n0 = (-_unit(pts[i - 1], pts[i])[1], _unit(pts[i - 1], pts[i])[0]) if i > 0 else None
        n1 = (-_unit(pts[i], pts[i + 1])[1], _unit(pts[i], pts[i + 1])[0]) if i < len(pts) - 1 else None
        if n0 is None or n1 is None:
            nx, ny = n1 or n0
        else:
            mx, my = n0[0] + n1[0], n0[1] + n1[1]
            ml = math.hypot(mx, my)
            if ml < 1e-9:
                nx, ny = n0
            else:
                mx, my = mx / ml, my / ml
                k = 1 / max(0.5, mx * n0[0] + my * n0[1])      # inglete, acotado a 2x
                nx, ny = mx * k, my * k
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    return tuple(left + right[::-1])


def arrow_path(a: Arrow) -> list[Point]:
    """Puntos por los que pasa una flecha o linea: recta (2 puntos), con un codo en angulo recto (3 o 4) o curva (la Bezier
    aplanada). Si start y end estan alineados el codo se reduce a la recta."""
    if a.route is ConnectorRoute.CURVE and a.curve_bend != 0 and a.start != a.end:
        return curve_points(a.start, a.end, a.curve_bend)
    if a.route is ConnectorRoute.ELBOW and a.elbow_z:   # Z: sale y llega en el mismo eje, con el tramo del medio en `elbow_split`
        (x1, y1), (x2, y2) = a.start, a.end
        if a.elbow_vertical_first:
            my = y1 + (y2 - y1) * a.elbow_split
            return lens.simplify_path([a.start, (x1, my), (x2, my), a.end])
        mx = x1 + (x2 - x1) * a.elbow_split
        return lens.simplify_path([a.start, (mx, y1), (mx, y2), a.end])
    if a.route is ConnectorRoute.ELBOW:
        horizontal, vertical = (1, 0), (0, 1)
        first, last = (vertical, horizontal) if a.elbow_vertical_first else (horizontal, vertical)
        return lens.orthogonal_path(a.start, first, a.end, last)
    return [a.start, a.end]


def _unit(a: Point, b: Point) -> Point:
    """Vector unitario de a hacia b (nulo si coinciden)."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length) if length else (0.0, 0.0)


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
    glow_strength: float = style.DEFAULT_GLOW_STRENGTH,
    glow_size: float = style.DEFAULT_GLOW_SIZE,
    path: Sequence[Point] | None = None,
    body: ArrowBody = ArrowBody.UNIFORM,
    head_size: float = 1.0,
    shadow: bool = False,
    shadow_strength: float = 1.0,
) -> list[Primitive]:
    """Linea de a hacia b con puntas opcionales en cada extremo, con la sombra y el resplandor debajo. `path` (de `arrow_path`)
    es el camino de a a b cuando lleva codo o curva; cada punta mira en la direccion del tramo en que termina el camino. Con
    `body=TAPERED` el cuerpo es un poligono conico (sin rayas) y `width` es su grosor maximo."""
    x1, y1 = a
    x2, y2 = b
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return []
    route = tuple(path) if path is not None and len(path) > 2 else (a, b)
    sw = width * scale
    head = style.ARROW_HEAD * scale * min(3.0, max(0.5, width / style.MARKER_STROKE)) * head_size   # la punta sigue al grosor
    ux, uy = _unit(route[-2], route[-1])
    sx, sy = _unit(route[1], route[0])
    dash, cap = dash_pattern(line_style, sw)
    extra = style.ARROW_GLOW_EXTRA * scale * glow_size
    glow_opacity = min(1.0, style.ARROW_GLOW_OPACITY * glow_strength)
    heads = [(h, p, d) for h, p, d in ((head_end, b, (ux, uy)), (head_start, a, (sx, sy))) if h is not HeadStyle.NONE]
    parts: list[Primitive] = []
    outline = tapered_outline(route, sw) if body is ArrowBody.TAPERED else ()
    if shadow:
        parts.extend(_arrow_shadow(route, outline, sw, heads, head, dash, cap, scale, shadow_strength))
    if outline:
        if glow:
            parts.append(PPolygon(outline, None, glow_color, extra, glow_opacity))
        parts.append(PPolygon(outline, color, None))
    else:
        if glow:
            parts.append(_connector_line(route, glow_color, sw + extra, glow_opacity, dash, cap))
        parts.append(_connector_line(route, color, sw, 1.0, dash, cap))
    for kind, point, (dx, dy) in heads:
        if kind is HeadStyle.DOT:
            radius = max(sw * 1.2, head * 0.35)
            if glow:
                parts.append(PCircle(point, radius, None, glow_color, extra, opacity=glow_opacity))
            parts.append(PCircle(point, radius, color, None))
        else:
            pts = _head_points(point, dx, dy, head)
            if glow:
                parts.append(PPolygon(pts, None, glow_color, extra, glow_opacity))
            parts.append(PPolygon(pts, color, None))
    return parts


def _arrow_shadow(
    route: Sequence[Point], outline: Sequence[Point], sw: float, heads: Sequence, head: float,
    dash: tuple[float, ...] | None, cap: str, scale: float, strength: float,
) -> list[Primitive]:
    """Sombra suave de una flecha: negro desplazado hacia abajo y 'desenfocado' con capas translucidas apiladas (de la mas ancha a
    un nucleo), sin filtros: asi Qt y el SVG coinciden pixel a pixel, igual que el resplandor."""
    black = "#000000"
    dy = style.ARROW_SHADOW_DY * scale
    shifted_route = tuple((x, y + dy) for x, y in route)
    shifted_outline = tuple((x, y + dy) for x, y in outline)
    layers = [(off * scale, op) for off, op in reversed(style.arrow_shadow_rings(strength))]
    layers.append((0.0, style.arrow_shadow_core(strength)))      # el nucleo, ultimo (el mas oscuro)
    out: list[Primitive] = []
    for off, op in layers:
        if shifted_outline:
            out.append(_shadow_polygon(shifted_outline, black, off, op))
        else:
            out.append(_connector_line(shifted_route, black, sw + 2 * off, op, dash, cap))
        for kind, point, (dx, dy_) in heads:
            moved = (point[0], point[1] + dy)
            if kind is HeadStyle.DOT:
                radius = max(sw * 1.2, head * 0.35) + off
                # un disco translucido: el PCircle solo tiene opacidad en el borde, asi que es un trazo grueso desde el centro
                out.append(PCircle(moved, radius / 2, None, black, radius, opacity=op))
            else:
                out.append(_shadow_polygon(tuple((x, y + dy) for x, y in _head_points(point, dx, dy_, head)), black, off, op))
    return out


def _shadow_polygon(points: Sequence[Point], color: str, off: float, opacity: float) -> PPolygon:
    """Una capa de la sombra: el nucleo (relleno translucido) o un anillo (solo borde translucido, `2 * off` de ancho)."""
    if off == 0:
        return PPolygon(tuple(points), color, None, 0.0, 1.0, opacity)
    return PPolygon(tuple(points), None, color, 2 * off, opacity)


def _arrow_parts(
    a: Point, b: Point, scale: float, glow: bool, color: str = style.RED, glow_color: str = style.GLOW_GOLD,
    glow_strength: float = style.DEFAULT_GLOW_STRENGTH, glow_size: float = style.DEFAULT_GLOW_SIZE,
) -> list[Primitive]:
    """Linea de a hacia b con punta en b, con el resplandor debajo (la flecha de siempre)."""
    return _line_parts(a, b, scale, glow, color, glow_color, glow_strength=glow_strength, glow_size=glow_size)


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
        for off, op in style.glow_rings(m.glow_strength, m.glow_size):
            o = off * scale
            out.append(PRect(m.rect.inflate(o), glow_color, style.glow_ring_width(m.glow_size) * scale, op, rx + o))
    out.append(PRect(m.rect, stroke, style.MARKER_STROKE * scale, 1.0, rx))
    if side is not ArrowSide.NONE:
        if m.custom_arrow:
            start, tip = m.arrow_start, m.arrow_tip
        else:
            start, tip = _marker_arrow_points(m.rect, side, scale)
        out.extend(_arrow_parts(start, tip, scale, m.glow, arrow_color, glow_color, m.glow_strength, m.glow_size))
    return out


def arrow_primitives(a: Arrow, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    return _line_parts(
        a.start, a.end, scale, a.glow, a.color or palette.arrow, a.glow_color or palette.glow,
        a.width, a.head_start, a.head_end, a.line_style, a.glow_strength, a.glow_size, arrow_path(a),
        a.body, a.head_size, a.shadow, a.shadow_strength,
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
        for off, op in style.glow_rings(s.glow_strength, s.glow_size):
            o = max(0.0, off + (s.border_width - style.MARKER_STROKE) / 2) * scale
            width = style.glow_ring_width(s.glow_size) * scale
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


def _soft_disc(center: Point, radius: float, color: str, opacity: float) -> PCircle:
    """Disco translucido: un circulo no tiene opacidad de relleno, asi que se pinta como un trazo grueso (radio r/2, ancho r)."""
    return PCircle(center, radius / 2, None, color, radius, opacity=opacity)


def icon_primitives(i: Icon, scale: float) -> list[Primitive]:
    """Resplandor, borde blanco, contenedor y simbolo de un icono. Todo sale de `icons` (coordenadas unitarias): el
    contenedor es un circulo salvo en la alerta (triangulo) y la estrella, que son su propio contenedor. En el estilo
    Solo simbolo no hay contenedor (la estrella lo conserva: no tiene otro simbolo)."""
    r = i.size * scale
    cx, cy = i.center
    color = i.color or style.ICON_COLORS[i.kind.value]
    light = style.ICON_LIGHT
    ring = style.ICON_RING * r if i.ring else 0.0
    glyph = icons.glyph(i.kind)
    polygon = icons.container_polygon(i.kind)
    boxed = i.style is not IconStyle.SYMBOL or not icons.has_glyph(i.kind)
    filled = i.style is not IconStyle.OUTLINE                     # contenedor de color (sello); el contorno va claro
    glyph_color = i.glyph_color or (light if filled and boxed and icons.has_glyph(i.kind) else color)
    boost = 1.0 if boxed else style.ICON_SYMBOL_BOOST
    sw = style.ICON_STROKE * r * (1.0 if boxed else 1.2)
    outline = style.ICON_OUTLINE * r
    corner = (0.16 if filled else style.ICON_OUTLINE) * r          # grosor del trazo que redondea las esquinas del poligono

    def pts(unit: Sequence[Point], k: float = 1.0) -> tuple[Point, ...]:
        return tuple((cx + x * r * k, cy + y * r * k) for x, y in unit)

    out: list[Primitive] = []
    if i.glow:
        glow_color = i.glow_color or style.GLOW_GOLD
        if boxed and polygon is None:   # anillos concentricos alrededor del circulo, como los del paso
            width = style.glow_ring_width(i.glow_size) * scale
            for off, op in style.glow_rings(i.glow_strength, i.glow_size):
                out.append(PCircle((cx, cy), r + off * scale, None, glow_color, width, opacity=op))
        elif boxed:   # triangulo y estrella: el contorno engrosado en capas (un desplazamiento parejo, sin picos)
            for off, op in reversed(style.glow_rings(i.glow_strength, i.glow_size)):
                out.append(PPolygon(pts(polygon), None, glow_color, corner + 2 * (ring + off * scale),
                                    op * style.CONNECTOR_GLOW_STRENGTH))
        else:       # solo simbolo: halo en capas pegado al trazo, como el del lapiz (de la mas ancha y tenue a la angosta)
            for off, op in reversed(style.glow_rings(i.glow_strength, i.glow_size)):
                o = off * scale
                for stroke in glyph.strokes:
                    out.append(PPolyline(pts(stroke, boost), glow_color, sw + 2 * (ring + o), op * style.CONNECTOR_GLOW_STRENGTH))
                for center, radius in glyph.dots:
                    out.append(_soft_disc(pts([center], boost)[0], radius * r * boost + ring + o, glow_color,
                                          op * style.CONNECTOR_GLOW_STRENGTH))
    if boxed:
        if polygon is None:
            if ring:
                out.append(PCircle((cx, cy), r + ring, light, None))
            if filled:
                out.append(PCircle((cx, cy), r, color, None))
            else:   # contorno: relleno claro con borde de color, por dentro del radio
                out.append(PCircle((cx, cy), r - outline / 2, light, color, outline))
        else:
            if ring:
                out.append(PPolygon(pts(polygon), light, light, corner + 2 * ring))
            out.append(PPolygon(pts(polygon), color if filled else light, color, corner))
    elif ring:   # solo simbolo: un halo blanco por debajo para que se lea sobre cualquier captura
        for stroke in glyph.strokes:
            out.append(PPolyline(pts(stroke, boost), light, sw + 2 * ring))
        for center, radius in glyph.dots:
            out.append(PCircle(pts([center], boost)[0], radius * r * boost + ring, light, None))
    for stroke in glyph.strokes:
        out.append(PPolyline(pts(stroke, boost), glyph_color, sw))
    for center, radius in glyph.dots:
        out.append(PCircle(pts([center], boost)[0], radius * r * boost, glyph_color, None))
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
        for off, op in reversed(style.glow_rings(s.glow_strength, s.glow_size)):
            out.append(PPolyline(curve, glow_color, width + 2 * off * scale, op * style.CONNECTOR_GLOW_STRENGTH))
    out.append(PPolyline(curve, color, width, s.opacity, "multiply" if s.mode is PenMode.MARKER else None))
    return out


def highlight_primitives(h: Highlight, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    blend = "multiply" if h.mode is HighlightMode.MARKER else None
    return [
        PRect(h.rect, None, 0.0, rx=h.radius * scale, fill=h.color or palette.highlight,
              fill_opacity=h.opacity, blend=blend)
    ]


def _connector_parts(m: Magnifier) -> list[tuple[Point, ...]]:
    """Lo que se dibuja del conector: una lista de caminos (de 2 puntos = una recta). Recto: una recta, o las dos
    tangentes del circulo; en codo: UN camino con sus esquinas."""
    path = lens.connector_path(m)
    if len(path) > 2:
        return [tuple(path)]
    return [(a, b) for a, b in lens.connector_segments(m)]


def _connector_line(
    part: tuple[Point, ...], stroke: str, width: float, opacity: float,
    dash: tuple[float, ...] | None = None, cap: str = "butt",
) -> Primitive:
    if len(part) == 2:
        return PLine(part[0], part[1], stroke, width, opacity, dash, cap)
    return PPath(part, stroke, width, opacity, dash, cap)


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
    connector_parts = _connector_parts(m)
    src_dash, src_cap = dash_pattern(m.source_style, src_w * scale)
    con_dash, con_cap = dash_pattern(m.connector_style, con_w * scale)
    frame_dash, frame_cap = dash_pattern(m.frame_style, fw * scale)
    out: list[Primitive] = []
    rx = lens.lens_corner_radius(m) if m.shape is LensShape.ROUNDED else 0.0

    if m.glow:
        # debajo de todo: el conector y el origen se dibujan encima, y la imagen del lente
        # tapa la parte de los anillos que cae dentro
        glow_color = m.glow_color or palette.glow
        for off, op in style.glow_rings(m.glow_strength, m.glow_size):
            o = (off + (fw - style.MARKER_STROKE) / 2) * scale
            width = style.glow_ring_width(m.glow_size) * scale
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
        for part in connector_parts:
            for off, op in reversed(style.glow_rings(m.glow_strength, m.glow_size)):
                out.append(_connector_line(
                    part, glow_color, con_w * scale + 2 * off * scale, op * style.CONNECTOR_GLOW_STRENGTH,
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

    for part in connector_parts:
        out.append(_connector_line(part, style.CARD_FILL, (con_w + 2) * scale, 0.6))
        out.append(_connector_line(part, con_color, con_w * scale, 1.0, con_dash, con_cap))

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
        return item.rect.inflate(style.glow_rings(item.glow_strength, item.glow_size)[-1][0] * scale)
    if isinstance(item, Arrow):
        x0, x1 = sorted((item.start[0], item.end[0]))
        y0, y1 = sorted((item.start[1], item.end[1]))
        return Rect(x0, y0, x1 - x0, y1 - y0).inflate(style.ARROW_HEAD * scale)
    if isinstance(item, StepBadge):
        r = step_extent(item, scale)
        return Rect(item.center[0] - r, item.center[1] - r, 2 * r, 2 * r)
    if isinstance(item, Icon):
        r = item.size * scale
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


def bracket_tip_item(b: Bracket, scale: float) -> TextLabel | Icon | None:
    """Lo que lleva el pico de una llave, ya colocado: una etiqueta de texto o un icono, FUERA de la forma, pasando el pico (separado
    `BRACKET_TIP_GAP`) y en la direccion en que este apunta, a cualquier angulo. None si el pico va vacio, el tramo no mide nada o no
    hay texto (ni el de una cota, que muestra su medida)."""
    tip = bracket_geometry.tip_point(b)
    if b.tip is TipContent.NONE or tip is None:
        return None
    no = bracket_geometry.outward(b)
    gap = style.BRACKET_TIP_GAP * scale
    if b.tip is TipContent.TEXT:
        text = bracket_geometry.label_text(b)
        if not text:
            return None
        preset = b.label_preset if b.label_preset in style.TEXT_PRESETS else "nota"
        label = replace(text_label_from_preset("tip", (0.0, 0.0), text, preset), size=b.label_size)
        box = label_box(label, scale)
        half = abs(no[0]) * box.w / 2 + abs(no[1]) * box.h / 2          # lo que la caja se asoma en la direccion del pico
        cx, cy = tip[0] + no[0] * (gap + half), tip[1] + no[1] * (gap + half)
        return replace(label, pos=(cx - box.w / 2, cy - box.h / 2))
    reach = gap + b.tip_icon_size * scale * 1.15                         # el radio del icono mas su borde
    return Icon("tip", (tip[0] + no[0] * reach, tip[1] + no[1] * reach), b.tip_icon, size=b.tip_icon_size)


def bracket_primitives(b: Bracket, scale: float, palette: Palette = BRAND_PALETTE) -> list[Primitive]:
    """La forma (polilineas de trazo redondo, con el halo en capas del resplandor debajo), las puntas de la cota y lo del pico."""
    paths = bracket_geometry.outline_paths(b)
    if not paths:
        return []
    color = b.color or palette.arrow
    width = b.width * scale
    out: list[Primitive] = []
    if b.glow:
        glow_color = b.glow_color or palette.glow
        for off, op in reversed(style.glow_rings(b.glow_strength, b.glow_size)):
            for path in paths:
                out.append(PPolyline(tuple(path), glow_color, width + 2 * off * scale, op * style.CONNECTOR_GLOW_STRENGTH))
    for path in paths:
        out.append(PPolyline(tuple(path), color, width))
    if b.kind is BracketKind.DIMENSION:
        line = paths[2]                                                   # la linea a `depth`: lleva una punta en cada extremo, hacia afuera
        head = style.ARROW_HEAD * scale * min(3.0, max(0.5, b.width / style.MARKER_STROKE)) * 0.8
        u = bracket_geometry.span(b)[0]
        out.append(PPolygon(_head_points(line[0], -u[0], -u[1], head), color, None))
        out.append(PPolygon(_head_points(line[1], u[0], u[1], head), color, None))
    tip = bracket_tip_item(b, scale)
    if isinstance(tip, TextLabel):
        out.extend(text_label_primitives(tip, scale))
    elif isinstance(tip, Icon):
        out.extend(icon_primitives(tip, scale))
    return out


def item_primitives(doc: AnnotationDoc, item: Annotation, scale: float) -> list[Primitive]:
    """Primitivas de una sola anotacion (las Redaction no generan: viven en el bitmap)."""
    if isinstance(item, Marker):
        side = resolve_arrow_side(item, doc.image_size, doc.items, scale, doc.view)
        return marker_primitives(item, scale, side, doc.palette)
    if isinstance(item, Arrow):
        return arrow_primitives(item, scale, doc.palette)
    if isinstance(item, StepBadge):
        return step_primitives(item, scale, doc.palette)
    if isinstance(item, Icon):
        return icon_primitives(item, scale)
    if isinstance(item, TextLabel):
        return text_label_primitives(item, scale)
    if isinstance(item, Magnifier):
        return magnifier_primitives(item, scale, doc.palette)
    if isinstance(item, Highlight):
        return highlight_primitives(item, scale, doc.palette)
    if isinstance(item, Stroke):
        return stroke_primitives(item, scale, doc.palette)
    if isinstance(item, Bracket):
        return bracket_primitives(item, scale, doc.palette)
    return []


def build_primitives(doc: AnnotationDoc) -> list[Primitive]:
    """Primitivas de todo el documento, en orden de dibujo. Las Redaction no
    generan primitivas: viven en el bitmap."""
    scale = doc_scale(doc)
    out: list[Primitive] = []
    for item in doc.items:
        out.extend(item_primitives(doc, item, scale))
    return out
