"""Geometria pura de la lupa: origen efectivo, lente, conector y colocacion
automatica. Sin Qt ni Pillow.

Formas: CIRCLE (origen cuadrado, lente circular), ELLIPSE (el origen y el lente son
ovalos con las proporciones del rectangulo arrastrado) y ROUNDED (rectangular, con
esquinas ajustables de rectas a muy redondeadas)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from core.annotate.model import ConnectorRoute, LensShape, Magnifier, Rect
from core.annotate.style import DEFAULT_LENS_CORNER

Point = tuple[float, float]

LENS_GAP = 28.0
MIN_ZOOM = 1.0
MAX_ZOOM = 8.0
RECOMMENDED_MAX_ZOOM = 3.0
MAX_CORNER = 0.5                         # 0.5 = esquinas tan redondeadas que el lente parece un capsula/ovalo
ROUNDED_RADIUS_RATIO = DEFAULT_LENS_CORNER


def effective_source(m: Magnifier) -> Rect:
    """Region realmente ampliada. Circular: cuadrado centrado de lado max(w, h). Ovalada y
    rectangular: el rectangulo tal cual (asi se conservan las proporciones arrastradas)."""
    s = m.source
    if m.shape is LensShape.CIRCLE:
        side = max(s.w, s.h)
        cx, cy = s.center
        return Rect(cx - side / 2, cy - side / 2, side, side)
    return s


def lens_size(m: Magnifier) -> tuple[float, float]:
    src = effective_source(m)
    return src.w * m.zoom, src.h * m.zoom


def lens_rect(m: Magnifier) -> Rect:
    w, h = lens_size(m)
    cx, cy = m.lens_center
    return Rect(cx - w / 2, cy - h / 2, w, h)


def lens_corner_radius(m: Magnifier) -> float:
    """Radio de las esquinas del lente rectangular: `corner` (0 a 0.5) por el lado menor."""
    w, h = lens_size(m)
    return min(w, h) * min(max(m.corner, 0.0), MAX_CORNER)


def crop_box(m: Magnifier) -> tuple[int, int, int, int]:
    src = effective_source(m)
    return round(src.x), round(src.y), round(src.right), round(src.bottom)


def is_crowded(m: Magnifier, margin: float = LENS_GAP / 2) -> bool:
    """True si el lente esta encima de su origen o mas cerca que `margin`: tan
    pegado que ni el conector se ve."""
    return lens_rect(m).inflate(margin).intersects(effective_source(m))


def _normalized_radius(rect: Rect, p: Point) -> float:
    """Distancia al centro en unidades del elipse inscrito: <1 dentro, 1 en el borde."""
    cx, cy = rect.center
    a, b = max(rect.w / 2, 1e-9), max(rect.h / 2, 1e-9)
    return math.hypot((p[0] - cx) / a, (p[1] - cy) / b)


def contains_in_lens(m: Magnifier, p: Point) -> bool:
    lens = lens_rect(m)
    if m.shape in (LensShape.CIRCLE, LensShape.ELLIPSE):
        return _normalized_radius(lens, p) <= 1.0
    return lens.x <= p[0] <= lens.right and lens.y <= p[1] <= lens.bottom


def near_source_border(m: Magnifier, p: Point, tol: float) -> bool:
    src = effective_source(m)
    if m.shape is LensShape.CIRCLE:
        cx, cy = src.center
        return abs(math.hypot(p[0] - cx, p[1] - cy) - src.w / 2) <= tol
    if m.shape is LensShape.ELLIPSE:
        # distancia aproximada al borde: diferencia de radio normalizado por el semieje menor
        return abs(_normalized_radius(src, p) - 1.0) * min(src.w, src.h) / 2 <= tol
    outer, inner = src.inflate(tol), src.inflate(-tol)

    def inside(r: Rect) -> bool:
        return r.x <= p[0] <= r.right and r.y <= p[1] <= r.bottom

    if src.w <= 2 * tol or src.h <= 2 * tol:
        return inside(outer)
    return inside(outer) and not inside(inner)


# --------------------------------------------------------------------------
# Conector
# --------------------------------------------------------------------------

def _tangent_segments(c1: Point, r1: float, c2: Point, r2: float) -> list[tuple[Point, Point]]:
    """Las dos tangentes externas entre dos circulos (un cono). Vacio si se tocan o se solapan."""
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d <= r1 + r2:
        return []
    phi = math.acos((r1 - r2) / d)
    ux, uy = dx / d, dy / d
    segments = []
    for sign in (1, -1):
        angle = sign * phi
        nx = ux * math.cos(angle) - uy * math.sin(angle)
        ny = ux * math.sin(angle) + uy * math.cos(angle)
        segments.append(((c1[0] + r1 * nx, c1[1] + r1 * ny), (c2[0] + r2 * nx, c2[1] + r2 * ny)))
    return segments


def _exit_distance(rect: Rect, ux: float, uy: float) -> float:
    """Distancia desde el centro del rectangulo hasta su borde en la direccion (ux, uy)."""
    candidates = []
    if ux:
        candidates.append(rect.w / 2 / abs(ux))
    if uy:
        candidates.append(rect.h / 2 / abs(uy))
    return min(candidates)


def _ellipse_exit_distance(rect: Rect, ux: float, uy: float) -> float:
    """Distancia desde el centro del elipse inscrito hasta su borde en la direccion (ux, uy)."""
    a, b = max(rect.w / 2, 1e-9), max(rect.h / 2, 1e-9)
    return 1.0 / math.hypot(ux / a, uy / b)


def _line_segment(src: Rect, lens: Rect, exit_distance) -> list[tuple[Point, Point]]:
    """Recta entre los bordes de las dos formas, sobre la linea de sus centros."""
    (x1, y1), (x2, y2) = src.center, lens.center
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d == 0:
        return []
    ux, uy = dx / d, dy / d
    t1 = exit_distance(src, ux, uy)
    t2 = exit_distance(lens, ux, uy)
    if t1 + t2 >= d:
        return []
    return [((x1 + ux * t1, y1 + uy * t1), (x2 - ux * t2, y2 - uy * t2))]


MIN_FACING_OVERLAP = 0.25   # fraccion del lado menor que deben compartir dos cajas para unirlas con una recta pareja


def _overlap_middle(a0: float, a1: float, b0: float, b1: float) -> float | None:
    """Mitad del tramo que comparten dos intervalos, si es de buen tamano; si no, None."""
    low, high = max(a0, b0), min(a1, b1)
    if high - low >= MIN_FACING_OVERLAP * min(a1 - a0, b1 - b0) and high > low:
        return (low + high) / 2
    return None


def _facing_anchors(src: Rect, box: Rect, share: bool = True) -> tuple[Point, Point] | None:
    """Extremos del conector de un lente rectangular: salen de los lados que se miran. Si las dos cajas comparten un
    tramo de ese lado el conector es PAREJO (horizontal o vertical, por la mitad del tramo compartido); si no, une la mitad
    de un lado con la mitad del otro. `share` False = siempre las mitades (los ovalos solo tocan su caja ahi). None si las
    cajas se tocan o se solapan en las dos direcciones (no cabe)."""
    dx, dy = box.center[0] - src.center[0], box.center[1] - src.center[1]
    gap_x = (box.x - src.right) if dx >= 0 else (src.x - box.right)
    gap_y = (box.y - src.bottom) if dy >= 0 else (src.y - box.bottom)
    if gap_x <= 0 and gap_y <= 0:
        return None
    if gap_x >= gap_y:   # uno a la derecha o a la izquierda del otro
        y = _overlap_middle(src.y, src.bottom, box.y, box.bottom) if share else None
        ya, yb = (y, y) if y is not None else (src.center[1], box.center[1])
        return ((src.right, ya), (box.x, yb)) if dx >= 0 else ((src.x, ya), (box.right, yb))
    x = _overlap_middle(src.x, src.right, box.x, box.right) if share else None
    xa, xb = (x, x) if x is not None else (src.center[0], box.center[0])
    return ((xa, src.bottom), (xb, box.y)) if dy >= 0 else ((xa, src.y), (xb, box.bottom))


def is_round(m: Magnifier) -> bool:
    return m.shape in (LensShape.CIRCLE, LensShape.ELLIPSE)


def border_fraction(rect: Rect, round_shape: bool, p: Point) -> tuple[float, float]:
    """El punto del borde de la caja (o del ovalo inscrito) mas cercano a `p`, como fraccion (u, v) de la caja."""
    if rect.w <= 0 or rect.h <= 0:
        return 0.5, 0.5
    cx, cy = rect.center
    if round_shape:
        ux, uy = p[0] - cx, p[1] - cy
        n = math.hypot(ux, uy)
        ux, uy = (ux / n, uy / n) if n > 1e-9 else (1.0, 0.0)
        t = _ellipse_exit_distance(rect, ux, uy)
        x, y = cx + ux * t, cy + uy * t
    else:
        x, y = min(max(p[0], rect.x), rect.right), min(max(p[1], rect.y), rect.bottom)   # fuera de la caja: ya cae en su borde
        if rect.x < p[0] < rect.right and rect.y < p[1] < rect.bottom:   # dentro: se manda al lado mas cercano
            to_edges = {"l": x - rect.x, "r": rect.right - x, "t": y - rect.y, "b": rect.bottom - y}
            side = min(to_edges, key=to_edges.get)
            x, y = {"l": (rect.x, y), "r": (rect.right, y), "t": (x, rect.y), "b": (x, rect.bottom)}[side]
    return (x - rect.x) / rect.w, (y - rect.y) / rect.h


def _from_fraction(rect: Rect, frac: tuple[float, float]) -> Point:
    return rect.x + frac[0] * rect.w, rect.y + frac[1] * rect.h


def _auto_anchors(m: Magnifier) -> tuple[Point, Point] | None:
    """Extremos del conector automatico (el del origen, el del lente) o None si no cabe."""
    src, box = effective_source(m), lens_rect(m)
    if m.shape is LensShape.ROUNDED:
        return _facing_anchors(src, box)
    if m.connector_route is ConnectorRoute.ELBOW:   # los ovalos salen por los puntos de sus ejes (los de sus lados)
        return _facing_anchors(src, box, share=False)
    seg = _line_segment(src, box, _ellipse_exit_distance if m.shape is LensShape.ELLIPSE else _circle_exit_distance)
    return seg[0] if seg else None


def _circle_exit_distance(rect: Rect, ux: float, uy: float) -> float:
    return rect.w / 2


def connector_anchors(m: Magnifier) -> tuple[Point, Point] | None:
    """Donde estan HOY los dos extremos del conector (los puestos a mano, o los automaticos): son donde van las asas.
    None si la lupa no lleva conector o no cabe."""
    if not m.connector:
        return None
    auto = _auto_anchors(m) if not (m.connector_start is not None and m.connector_end is not None) else None
    src, box = effective_source(m), lens_rect(m)
    a = _from_fraction(src, m.connector_start) if m.connector_start is not None else (auto[0] if auto else None)
    b = _from_fraction(box, m.connector_end) if m.connector_end is not None else (auto[1] if auto else None)
    if a is None or b is None or math.hypot(b[0] - a[0], b[1] - a[1]) < 1.0:
        return None
    return a, b


def connector_segments(m: Magnifier) -> list[tuple[Point, Point]]:
    if not m.connector:
        return []
    if m.connector_route is ConnectorRoute.ELBOW:
        path = connector_path(m)
        return list(zip(path, path[1:]))
    if m.custom_connector:
        anchors = connector_anchors(m)
        return [anchors] if anchors else []
    src, box = effective_source(m), lens_rect(m)
    if m.shape is LensShape.CIRCLE:
        return _tangent_segments(src.center, src.w / 2, box.center, box.w / 2)   # el cono de siempre
    anchors = _auto_anchors(m)
    return [anchors] if anchors else []


ELBOW_CLEARANCE = 20.0   # cuanto sale el codo del borde cuando los dos extremos miran al mismo lado


def _exit_direction(rect: Rect, round_shape: bool, p: Point) -> tuple[int, int]:
    """Direccion (de eje) hacia afuera de la caja o del ovalo en el punto `p` de su borde."""
    if round_shape:
        dx, dy = (p[0] - rect.center[0]) / max(rect.w / 2, 1e-9), (p[1] - rect.center[1]) / max(rect.h / 2, 1e-9)
        if abs(dx) >= abs(dy):
            return (1 if dx >= 0 else -1), 0
        return 0, (1 if dy >= 0 else -1)
    sides = {(-1, 0): p[0] - rect.x, (1, 0): rect.right - p[0], (0, -1): p[1] - rect.y, (0, 1): rect.bottom - p[1]}
    return min(sides, key=sides.get)   # el lado mas cercano (en una esquina gana el horizontal)


def simplify_path(points: list[Point]) -> list[Point]:
    """Sin puntos repetidos ni puntos de en medio de un tramo recto."""
    out: list[Point] = []
    for p in points:
        if out and math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) < 1e-6:
            continue
        while len(out) >= 2 and ((out[-2][0] == out[-1][0] == p[0]) or (out[-2][1] == out[-1][1] == p[1])):
            out.pop()
        out.append(p)
    return out


def orthogonal_path(a: Point, da: tuple[int, int], b: Point, db: tuple[int, int]) -> list[Point]:
    """Camino de a a b con tramos horizontales y verticales. `da` y `db` son las direcciones hacia afuera de la forma en
    cada extremo: el camino sale de `a` hacia `da` y llega a `b` desde `db`."""
    horizontal_a, horizontal_b = da[0] != 0, db[0] != 0
    if horizontal_a and horizontal_b:   # Z: sale y llega en horizontal
        if da == db:   # los dos miran al mismo lado: el tramo del medio queda fuera de los dos
            mx = (max(a[0], b[0]) + ELBOW_CLEARANCE) if da[0] > 0 else (min(a[0], b[0]) - ELBOW_CLEARANCE)
        else:
            mx = (a[0] + b[0]) / 2
        return simplify_path([a, (mx, a[1]), (mx, b[1]), b])
    if not horizontal_a and not horizontal_b:   # Z: sale y llega en vertical
        if da == db:
            my = (max(a[1], b[1]) + ELBOW_CLEARANCE) if da[1] > 0 else (min(a[1], b[1]) - ELBOW_CLEARANCE)
        else:
            my = (a[1] + b[1]) / 2
        return simplify_path([a, (a[0], my), (b[0], my), b])
    if horizontal_a:   # L: sale en horizontal y llega en vertical
        return simplify_path([a, (b[0], a[1]), b])
    return simplify_path([a, (a[0], b[1]), b])


def connector_path(m: Magnifier) -> list[Point]:
    """Puntos del conector en codo (vacio si no hay conector o no es en codo). Con los extremos alineados se reduce a
    una recta de dos puntos."""
    if not m.connector or m.connector_route is not ConnectorRoute.ELBOW:
        return []
    anchors = connector_anchors(m)
    if anchors is None:
        return []
    a, b = anchors
    src, box, round_shape = effective_source(m), lens_rect(m), is_round(m)
    return orthogonal_path(a, _exit_direction(src, round_shape, a), b, _exit_direction(box, round_shape, b))


# --------------------------------------------------------------------------
# Colocacion automatica
# --------------------------------------------------------------------------

def default_lens_center(
    source: Rect,
    zoom: float,
    shape: LensShape,
    image_size: tuple[int, int],
    obstacles: Sequence[Rect] = (),
    gap: float = LENS_GAP,
    region: Rect | None = None,
) -> Point:
    """Centro del lente en el lado del origen con mas espacio libre, sin cubrir
    el origen ni salirse de la imagen (o de `region`, la parte visible si hay
    recorte) ni pisar los obstaculos. Si ningun lado cumple, el de mas espacio,
    recortado para que quepa lo mejor posible."""
    probe = Magnifier("probe", source, source.center, zoom, shape)
    src = effective_source(probe)
    w, h = lens_size(probe)
    area = region or Rect(0.0, 0.0, float(image_size[0]), float(image_size[1]))
    cx, cy = src.center
    candidates = [
        (area.right - src.right, (src.right + gap + w / 2, cy)),
        (src.x - area.x, (src.x - gap - w / 2, cy)),
        (area.bottom - src.bottom, (cx, src.bottom + gap + h / 2)),
        (src.y - area.y, (cx, src.y - gap - h / 2)),
    ]
    ordered = sorted(candidates, key=lambda c: -c[0])

    def box(center: Point) -> Rect:
        return Rect(center[0] - w / 2, center[1] - h / 2, w, h)

    def fits(center: Point) -> bool:
        b = box(center)
        inside = b.x >= area.x and b.y >= area.y and b.right <= area.right and b.bottom <= area.bottom
        return inside and not any(b.intersects(o) for o in obstacles)

    for _free, center in ordered:
        if fits(center):
            return center

    def clamped(center: Point) -> Point:
        x = min(max(center[0], area.x + w / 2), area.right - w / 2) if w <= area.w else area.x + area.w / 2
        y = min(max(center[1], area.y + h / 2), area.bottom - h / 2) if h <= area.h else area.y + area.h / 2
        return x, y

    def overlap(a: Rect, b: Rect) -> float:
        dx = min(a.right, b.right) - max(a.x, b.x)
        dy = min(a.bottom, b.bottom) - max(a.y, b.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def cost(center: Point) -> float:
        b = box(center)
        return overlap(b, src) * 1000 + sum(overlap(b, o) for o in obstacles)

    # nada cabe limpio: el candidato que menos estorbe (cubrir el origen es lo peor)
    return min((clamped(c) for _free, c in ordered), key=cost)
