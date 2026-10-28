"""Logica pura de edicion: hit-testing, asas de redimensionado, mover y
redimensionar. Sin Qt, para poder testear la interaccion sin ventana. Todas las
coordenadas estan en pixeles de la imagen fuente; `tol` es la tolerancia de
clic ya convertida a esos pixeles."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import Enum

from core.annotate import freehand, lens, style
from core.annotate.model import (
    Annotation,
    Arrow,
    ConnectorRoute,
    Highlight,
    Icon,
    ImageOverlay,
    Magnifier,
    Marker,
    Rect,
    Redaction,
    Spotlight,
    StepBadge,
    StepShape,
    Stroke,
    TextLabel,
)
from core.annotate.primitives import arrow_path, label_box, step_extent, stroke_curve

Point = tuple[float, float]


class Handle(str, Enum):
    NW = "nw"
    N = "n"
    NE = "ne"
    E = "e"
    SE = "se"
    S = "s"
    SW = "sw"
    W = "w"
    START = "start"
    END = "end"
    LENS = "lens"
    CONN_START = "conn_start"   # extremo del conector de la lupa que toca el origen
    CONN_END = "conn_end"       # el que toca el lente
    MID = "mid"                 # tramo del medio de una flecha en Z: arrastrarlo lo desplaza a lo largo del recorrido


MID_SNAP = 0.03   # al soltar el tramo del medio a menos de esto del centro (de 0 a 1) se queda justo en el centro

CONNECTOR_HANDLE_CLEARANCE = 12.0   # px de la imagen: un asa lateral del origen tan cerca de un extremo del conector le cede el lugar

_WEST = (Handle.NW, Handle.W, Handle.SW)
_EAST = (Handle.NE, Handle.E, Handle.SE)
_NORTH = (Handle.NW, Handle.N, Handle.NE)
_SOUTH = (Handle.SW, Handle.S, Handle.SE)


def new_id(items: Sequence[Annotation], prefix: str = "a") -> str:
    """Id unico dentro del documento: a1, a2, ..."""
    used = [int(m.group(1)) for i in items if (m := re.fullmatch(rf"{prefix}(\d+)", i.id))]
    return f"{prefix}{max(used, default=0) + 1}"


def next_step_number(items: Sequence[Annotation]) -> int:
    return max((i.number for i in items if isinstance(i, StepBadge)), default=0) + 1


def find_index(items: Sequence[Annotation], item_id: str) -> int | None:
    for index, item in enumerate(items):
        if item.id == item_id:
            return index
    return None


def clamp_point(point: Point, size: tuple[int, int]) -> Point:
    return min(max(0.0, point[0]), float(size[0])), min(max(0.0, point[1]), float(size[1]))


def distance_to_segment(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _contains(rect: Rect, p: Point) -> bool:
    return rect.x <= p[0] <= rect.right and rect.y <= p[1] <= rect.bottom


# --------------------------------------------------------------------------
# Hit-testing
# --------------------------------------------------------------------------

Arrows = Mapping[str, tuple[Point, Point]]   # id de marcador -> (inicio, punta) de su flecha


def hit_item(
    item: Annotation, p: Point, tol: float, scale: float, arrows: Arrows | None = None
) -> bool:
    if isinstance(item, Marker):
        outer = item.rect.inflate(tol)
        inner = item.rect.inflate(-tol)
        arrow = (arrows or {}).get(item.id)
        if arrow is not None and distance_to_segment(p, arrow[0], arrow[1]) <= tol:
            return True   # la flecha del marcador tambien cuenta
        if item.rect.w <= 2 * tol or item.rect.h <= 2 * tol:
            return _contains(outer, p)
        return _contains(outer, p) and not _contains(inner, p)
    if isinstance(item, Redaction):
        return _contains(item.rect.inflate(tol), p)
    if isinstance(item, Spotlight):
        # solo el borde de la zona: el interior (y todo el fondo) deja pasar el clic a lo que hay debajo
        r = item.rect
        if r.w <= 2 * tol or r.h <= 2 * tol:
            return _contains(r.inflate(tol), p)
        return _contains(r.inflate(tol), p) and not _contains(r.inflate(-tol), p)
    if isinstance(item, ImageOverlay):
        return _contains(item.rect.inflate(tol / 2), p)
    if isinstance(item, Highlight):
        return _contains(item.rect.inflate(tol / 2), p)
    if isinstance(item, Stroke):
        return freehand.distance_to_polyline(p, stroke_curve(item)) <= item.width * scale / 2 + tol
    if isinstance(item, Arrow):
        path = arrow_path(item)
        return any(distance_to_segment(p, a, b) <= tol for a, b in zip(path, path[1:]))
    if isinstance(item, StepBadge):
        dx, dy = abs(p[0] - item.center[0]), abs(p[1] - item.center[1])
        reach = step_extent(item, scale) + tol / 2
        if item.shape is StepShape.CIRCLE:
            return math.hypot(dx, dy) <= reach
        if item.shape is StepShape.DIAMOND:
            return dx + dy <= reach
        return dx <= reach and dy <= reach
    if isinstance(item, Icon):
        return math.hypot(p[0] - item.center[0], p[1] - item.center[1]) <= item.size * scale + tol / 2
    if isinstance(item, TextLabel):
        return _contains(label_box(item, scale).inflate(tol / 2), p)
    if isinstance(item, Magnifier):
        return hit_lens_part(item, p, tol) is not None
    return False


def hit_lens_part(m: Magnifier, p: Point, tol: float) -> str | None:
    """Que parte de la lupa esta bajo el punto: 'lens' (el cuerpo del lente, gana si
    se solapan), 'source' (el borde de la zona de origen) o 'connector' (la linea que los une)."""
    if lens.contains_in_lens(m, p):
        return "lens"
    if lens.near_source_border(m, p, tol):
        return "source"
    if any(distance_to_segment(p, a, b) <= tol for a, b in lens.connector_segments(m)):
        return "connector"
    return None


def hit_test(
    items: Sequence[Annotation], p: Point, tol: float, scale: float, arrows: Arrows | None = None
) -> str | None:
    """Id de la anotacion mas arriba (la ultima dibujada) bajo el punto. Un marcador solo
    responde en su borde y su flecha (asi se puede seleccionar lo que hay DENTRO de el);
    si no hay nada mas bajo el punto, su interior tambien lo selecciona."""
    for item in reversed(items):
        if not isinstance(item, ImageOverlay) and hit_item(item, p, tol, scale, arrows):
            return item.id
    # las imagenes pegadas van DEBAJO de las anotaciones (se componen en el bitmap): solo cuentan si no hay otra cosa
    for item in reversed(items):
        if isinstance(item, ImageOverlay) and hit_item(item, p, tol, scale, arrows):
            return item.id
    for item in reversed(items):
        if isinstance(item, (Marker, Spotlight)) and _contains(item.rect.inflate(tol), p):
            return item.id
    return None


def rect_handles(r: Rect) -> dict[Handle, Point]:
    cx, cy = r.center
    return {
        Handle.NW: (r.x, r.y), Handle.N: (cx, r.y), Handle.NE: (r.right, r.y),
        Handle.E: (r.right, cy), Handle.SE: (r.right, r.bottom), Handle.S: (cx, r.bottom),
        Handle.SW: (r.x, r.bottom), Handle.W: (r.x, cy),
    }


def item_handles(item: Annotation, arrows: Arrows | None = None) -> dict[Handle, Point]:
    """Asas de redimensionado: 8 para rectangulos, 2 para flechas, para la lupa
    las 8 de su origen mas una (LENS) en la esquina del lente que cambia el zoom, y los dos extremos de su conector
    (CONN_START y CONN_END; donde coinciden con un asa lateral del origen, esta cede su lugar). Un marcador
    con flecha suma START (la cola) y END (la punta) de la flecha, que se pueden arrastrar."""
    if isinstance(item, Marker):
        handles = rect_handles(item.rect)
        arrow = (arrows or {}).get(item.id)
        if arrow is not None:
            handles[Handle.START], handles[Handle.END] = arrow
        return handles
    if isinstance(item, (Redaction, Highlight, Spotlight, ImageOverlay)):
        return rect_handles(item.rect)
    if isinstance(item, Stroke):
        return rect_handles(_stroke_box(item)) if item.points else {}
    if isinstance(item, Magnifier):
        handles = rect_handles(lens.effective_source(item))
        box = lens.lens_rect(item)
        handles[Handle.LENS] = (box.right, box.bottom)
        anchors = lens.connector_anchors(item)
        if anchors is not None:
            for handle in [h for h, pos in handles.items() if h is not Handle.LENS and any(
                    math.hypot(pos[0] - a[0], pos[1] - a[1]) < CONNECTOR_HANDLE_CLEARANCE for a in anchors)]:
                del handles[handle]
            handles[Handle.CONN_START], handles[Handle.CONN_END] = anchors
        return handles
    if isinstance(item, Arrow):
        handles = {Handle.START: item.start, Handle.END: item.end}
        mid = z_middle_handle(item)
        if mid is not None:
            handles[Handle.MID] = mid
        return handles
    return {}


def z_middle_handle(a: Arrow) -> Point | None:
    """Donde esta el asa del tramo del medio de una flecha en Z (la mitad de ese tramo); None si no es Z o si no hay recorrido
    en el eje en que se desplaza (inicio y final a la misma x, o a la misma y si sale en vertical)."""
    if a.route is not ConnectorRoute.ELBOW or not a.elbow_z:
        return None
    (x1, y1), (x2, y2) = a.start, a.end
    if a.elbow_vertical_first:
        return None if y1 == y2 else ((x1 + x2) / 2, y1 + (y2 - y1) * a.elbow_split)
    return None if x1 == x2 else (x1 + (x2 - x1) * a.elbow_split, (y1 + y2) / 2)


def hit_handle(item: Annotation, p: Point, tol: float, arrows: Arrows | None = None) -> Handle | None:
    """Asa bajo el punto; si hay varias cerca gana la mas cercana."""
    best: tuple[float, Handle] | None = None
    for handle, pos in item_handles(item, arrows).items():
        d = math.hypot(p[0] - pos[0], p[1] - pos[1])
        if d <= tol and (best is None or d < best[0]):
            best = (d, handle)
    return best[1] if best else None


def _stroke_box(s: Stroke) -> Rect:
    """Caja de los puntos de control de un trazo (sin su grosor): de ella salen las asas de escalado."""
    x, y, w, h = freehand.bounding_box(s.points)
    return Rect(x, y, w, h)


def selection_rect(item: Annotation, scale: float) -> Rect:
    """Caja que se dibuja alrededor de la anotacion seleccionada."""
    if isinstance(item, Stroke):
        return _stroke_box(item).inflate(item.width * scale / 2) if item.points else Rect(0, 0, 0, 0)
    if isinstance(item, (Marker, Redaction, Highlight, Spotlight, ImageOverlay)):
        return item.rect
    if isinstance(item, Arrow):
        x0, x1 = sorted((item.start[0], item.end[0]))
        y0, y1 = sorted((item.start[1], item.end[1]))
        return Rect(x0, y0, x1 - x0, y1 - y0)
    if isinstance(item, StepBadge):
        r = step_extent(item, scale)
        return Rect(item.center[0] - r, item.center[1] - r, 2 * r, 2 * r)
    if isinstance(item, Icon):
        r = item.size * scale
        return Rect(item.center[0] - r, item.center[1] - r, 2 * r, 2 * r)
    if isinstance(item, Magnifier):
        return lens.lens_rect(item)
    return label_box(item, scale)


def selection_rects(item: Annotation, scale: float) -> list[Rect]:
    """Cajas a dibujar: la lupa muestra su origen y su lente; el resto, una."""
    if isinstance(item, Magnifier):
        return [lens.effective_source(item), lens.lens_rect(item)]
    return [selection_rect(item, scale)]


# --------------------------------------------------------------------------
# Mover y redimensionar (devuelven una anotacion nueva; las originales son inmutables)
# --------------------------------------------------------------------------

def hit_marker_part(m: Marker, p: Point, tol: float, arrows: Arrows | None = None) -> str | None:
    """'arrow' si el punto esta sobre la flecha del marcador (mas cerca de ella que del borde del
    recuadro): arrastrar ahi mueve solo la flecha; None = el marcador completo."""
    arrow = (arrows or {}).get(m.id)
    if arrow is None:
        return None
    d_arrow = distance_to_segment(p, arrow[0], arrow[1])
    return "arrow" if d_arrow <= tol and d_arrow < _distance_to_border(m.rect, p) else None


def _distance_to_border(rect: Rect, p: Point) -> float:
    """Distancia del punto al contorno del rectangulo (dentro o fuera)."""
    dx = max(rect.x - p[0], 0.0, p[0] - rect.right)
    dy = max(rect.y - p[1], 0.0, p[1] - rect.bottom)
    if dx or dy:
        return math.hypot(dx, dy)
    return min(p[0] - rect.x, rect.right - p[0], p[1] - rect.y, rect.bottom - p[1])


def move_item(
    item: Annotation, dx: float, dy: float, part: str | None = None, arrows: Arrows | None = None
) -> Annotation:
    """part: para la lupa, 'lens' mueve el lente, 'source' el origen, otro valor mueve ambos; para
    un marcador, 'arrow' mueve solo su flecha (necesita `arrows` para saber donde esta) y otro
    valor mueve el marcador con su flecha."""
    if isinstance(item, Magnifier):
        s, c = item.source, item.lens_center
        moved_source = Rect(s.x + dx, s.y + dy, s.w, s.h)
        moved_center = (c[0] + dx, c[1] + dy)
        if part == "lens":
            return replace(item, lens_center=moved_center)
        if part == "source":
            return replace(item, source=moved_source)
        return replace(item, source=moved_source, lens_center=moved_center)
    if isinstance(item, Marker):
        if part == "arrow":
            arrow = (arrows or {}).get(item.id)
            if arrow is None:
                return item
            (sx, sy), (tx, ty) = arrow
            return replace(item, arrow_start=(sx + dx, sy + dy), arrow_tip=(tx + dx, ty + dy))
        r = item.rect
        moved = replace(item, rect=Rect(r.x + dx, r.y + dy, r.w, r.h))
        if item.custom_arrow:   # la flecha puesta a mano viaja con el marcador
            moved = replace(
                moved,
                arrow_start=(item.arrow_start[0] + dx, item.arrow_start[1] + dy),
                arrow_tip=(item.arrow_tip[0] + dx, item.arrow_tip[1] + dy),
            )
        return moved
    if isinstance(item, (Redaction, Highlight, Spotlight, ImageOverlay)):
        r = item.rect
        return replace(item, rect=Rect(r.x + dx, r.y + dy, r.w, r.h))
    if isinstance(item, Stroke):
        return replace(item, points=tuple((x + dx, y + dy) for x, y in item.points))
    if isinstance(item, Arrow):
        return replace(
            item,
            start=(item.start[0] + dx, item.start[1] + dy),
            end=(item.end[0] + dx, item.end[1] + dy),
        )
    if isinstance(item, (StepBadge, Icon)):
        return replace(item, center=(item.center[0] + dx, item.center[1] + dy))
    if isinstance(item, TextLabel):
        return replace(item, pos=(item.pos[0] + dx, item.pos[1] + dy))
    return item


def resize_item(
    item: Annotation, handle: Handle, p: Point, min_size: float = 4.0, arrows: Arrows | None = None, free: bool = False
) -> Annotation:
    """Mueve el asa al punto. Los rectangulos nunca bajan de min_size; si se
    arrastra el asa mas alla del lado opuesto, se queda en min_size. En un marcador, START y
    END mueven la cola o la punta de su flecha (la otra punta se queda donde estaba)."""
    if isinstance(item, Stroke):
        return _resize_stroke(item, handle, p, min_size)
    if isinstance(item, Marker) and handle in (Handle.START, Handle.END):
        arrow = (arrows or {}).get(item.id)
        if arrow is None:
            return item
        start, tip = arrow
        if handle is Handle.START:
            start = p
        else:
            tip = p
        return replace(item, arrow_start=start, arrow_tip=tip)
    if isinstance(item, Arrow):
        if handle is Handle.START:
            return replace(item, start=p)
        if handle is Handle.END:
            return replace(item, end=p)
        if handle is Handle.MID and z_middle_handle(item) is not None:
            (x1, y1), (x2, y2) = item.start, item.end
            split = (p[1] - y1) / (y2 - y1) if item.elbow_vertical_first else (p[0] - x1) / (x2 - x1)
            split = min(1.0, max(0.0, split))
            return replace(item, elbow_split=0.5 if abs(split - 0.5) < MID_SNAP else split)
        return item
    if isinstance(item, Magnifier):
        return _resize_lens(item, handle, p, min_size)
    if isinstance(item, ImageOverlay):
        return _resize_overlay(item, handle, p, max(min_size, style.MIN_OVERLAY_SIZE), free)
    if not isinstance(item, (Marker, Redaction, Highlight, Spotlight)):
        return item
    return replace(item, rect=resize_rect(item.rect, handle, p, min_size))


def _resize_overlay(item: ImageOverlay, handle: Handle, p: Point, min_size: float, free: bool) -> ImageOverlay:
    """Una imagen pegada conserva la PROPORCION de su original (que no se deforme); con `free` (Mayus mientras se arrastra)
    se estira como cualquier rectangulo. Una esquina deja fija la opuesta; un lado, el lado contrario, y la otra medida
    sigue la proporcion alrededor de su centro."""
    if free or item.size[0] <= 0 or item.size[1] <= 0:
        return replace(item, rect=resize_rect(item.rect, handle, p, min_size))
    ratio = item.size[0] / item.size[1]
    r = item.rect
    min_w = max(min_size, min_size * ratio)
    min_h = max(min_size, min_size / ratio)
    if handle in (Handle.NW, Handle.NE, Handle.SE, Handle.SW):
        ax = r.right if handle in _WEST else r.x
        ay = r.bottom if handle in _NORTH else r.y
        w = (ax - p[0]) if handle in _WEST else (p[0] - ax)
        h = (ay - p[1]) if handle in _NORTH else (p[1] - ay)
        w = max(w, h * ratio, min_w)
        h = w / ratio
        x = ax - w if handle in _WEST else ax
        y = ay - h if handle in _NORTH else ay
    elif handle in (Handle.E, Handle.W):
        ax = r.right if handle is Handle.W else r.x
        w = max(min_w, (ax - p[0]) if handle is Handle.W else (p[0] - ax))
        h = w / ratio
        x = ax - w if handle is Handle.W else ax
        y = r.center[1] - h / 2
    elif handle in (Handle.N, Handle.S):
        ay = r.bottom if handle is Handle.N else r.y
        h = max(min_h, (ay - p[1]) if handle is Handle.N else (p[1] - ay))
        w = h * ratio
        x = r.center[0] - w / 2
        y = ay - h if handle is Handle.N else ay
    else:
        return item
    return replace(item, rect=Rect(x, y, w, h))


def _resize_stroke(s: Stroke, handle: Handle, p: Point, min_size: float) -> Stroke:
    """Escala los puntos del trazo: su caja pasa de la actual a la que da mover el asa (el grosor no cambia)."""
    if not s.points:
        return s
    old = _stroke_box(s)
    new = resize_rect(old, handle, p, min_size)
    sx = new.w / old.w if old.w > 1e-9 else 1.0
    sy = new.h / old.h if old.h > 1e-9 else 1.0
    return replace(s, points=tuple(((x - old.x) * sx + new.x, (y - old.y) * sy + new.y) for x, y in s.points))


def _resize_lens(m: Magnifier, handle: Handle, p: Point, min_size: float) -> Magnifier:
    """El asa LENS cambia el zoom anclando la esquina superior izquierda del lente;
    las demas redimensionan la zona de origen."""
    if handle is Handle.CONN_START:
        return replace(m, connector_start=lens.border_fraction(lens.effective_source(m), lens.is_round(m), p))
    if handle is Handle.CONN_END:
        return replace(m, connector_end=lens.border_fraction(lens.lens_rect(m), lens.is_round(m), p))
    if handle is not Handle.LENS:
        return replace(m, source=resize_rect(lens.effective_source(m), handle, p, min_size))
    box, src = lens.lens_rect(m), lens.effective_source(m)
    zoom = max((p[0] - box.x) / src.w, (p[1] - box.y) / src.h)
    zoom = min(max(zoom, lens.MIN_ZOOM), lens.MAX_ZOOM)
    return replace(m, zoom=zoom, lens_center=(box.x + src.w * zoom / 2, box.y + src.h * zoom / 2))


def resize_rect(r: Rect, handle: Handle, p: Point, min_size: float) -> Rect:
    left, top, right, bottom = r.x, r.y, r.right, r.bottom
    if handle in _WEST:
        left = p[0]
    if handle in _EAST:
        right = p[0]
    if handle in _NORTH:
        top = p[1]
    if handle in _SOUTH:
        bottom = p[1]
    if right - left < min_size:
        if handle in _WEST:
            left = right - min_size
        else:
            right = left + min_size
    if bottom - top < min_size:
        if handle in _NORTH:
            top = bottom - min_size
        else:
            bottom = top + min_size
    return Rect(left, top, right - left, bottom - top)


def rect_from_points(a: Point, b: Point) -> Rect:
    """Rectangulo normalizado entre dos esquinas cualesquiera."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    return Rect(x0, y0, x1 - x0, y1 - y0)
