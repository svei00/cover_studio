"""Geometria pura de la lupa: origen efectivo, lente, conector y colocacion
automatica. Sin Qt ni Pillow."""

from __future__ import annotations

import math
from collections.abc import Sequence

from core.annotate.model import LensShape, Magnifier, Rect

Point = tuple[float, float]

LENS_GAP = 28.0
MIN_ZOOM = 1.0
MAX_ZOOM = 8.0
RECOMMENDED_MAX_ZOOM = 3.0
ROUNDED_RADIUS_RATIO = 0.12


def effective_source(m: Magnifier) -> Rect:
    """Region realmente ampliada. Circular: cuadrado centrado de lado max(w, h)."""
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
    """Radio de las esquinas del lente rectangular, proporcional a su tamano."""
    w, h = lens_size(m)
    return min(w, h) * ROUNDED_RADIUS_RATIO


def crop_box(m: Magnifier) -> tuple[int, int, int, int]:
    src = effective_source(m)
    return round(src.x), round(src.y), round(src.right), round(src.bottom)


def is_crowded(m: Magnifier, margin: float = LENS_GAP / 2) -> bool:
    """True si el lente esta encima de su origen o mas cerca que `margin`: tan
    pegado que ni el conector se ve."""
    return lens_rect(m).inflate(margin).intersects(effective_source(m))


def contains_in_lens(m: Magnifier, p: Point) -> bool:
    lens = lens_rect(m)
    if m.shape is LensShape.CIRCLE:
        cx, cy = lens.center
        return math.hypot(p[0] - cx, p[1] - cy) <= lens.w / 2
    return lens.x <= p[0] <= lens.right and lens.y <= p[1] <= lens.bottom


def near_source_border(m: Magnifier, p: Point, tol: float) -> bool:
    src = effective_source(m)
    if m.shape is LensShape.CIRCLE:
        cx, cy = src.center
        return abs(math.hypot(p[0] - cx, p[1] - cy) - src.w / 2) <= tol
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


def _rect_segment(src: Rect, lens: Rect) -> list[tuple[Point, Point]]:
    """Recta entre los bordes de los dos rectangulos, sobre la linea de sus centros."""
    (x1, y1), (x2, y2) = src.center, lens.center
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d == 0:
        return []
    ux, uy = dx / d, dy / d
    t1 = _exit_distance(src, ux, uy)
    t2 = _exit_distance(lens, ux, uy)
    if t1 + t2 >= d:
        return []
    return [((x1 + ux * t1, y1 + uy * t1), (x2 - ux * t2, y2 - uy * t2))]


def connector_segments(m: Magnifier) -> list[tuple[Point, Point]]:
    if not m.connector:
        return []
    src, lens = effective_source(m), lens_rect(m)
    if m.shape is LensShape.CIRCLE:
        return _tangent_segments(src.center, src.w / 2, lens.center, lens.w / 2)
    return _rect_segment(src, lens)


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
) -> Point:
    """Centro del lente en el lado del origen con mas espacio libre, sin cubrir
    el origen ni salirse de la imagen ni pisar los obstaculos. Si ningun lado
    cumple, el de mas espacio, recortado para que quepa lo mejor posible."""
    probe = Magnifier("probe", source, source.center, zoom, shape)
    src = effective_source(probe)
    w, h = lens_size(probe)
    iw, ih = image_size
    cx, cy = src.center
    candidates = [
        (iw - src.right, (src.right + gap + w / 2, cy)),
        (src.x, (src.x - gap - w / 2, cy)),
        (ih - src.bottom, (cx, src.bottom + gap + h / 2)),
        (src.y, (cx, src.y - gap - h / 2)),
    ]
    ordered = sorted(candidates, key=lambda c: -c[0])

    def box(center: Point) -> Rect:
        return Rect(center[0] - w / 2, center[1] - h / 2, w, h)

    def fits(center: Point) -> bool:
        b = box(center)
        inside = b.x >= 0 and b.y >= 0 and b.right <= iw and b.bottom <= ih
        return inside and not any(b.intersects(o) for o in obstacles)

    for _free, center in ordered:
        if fits(center):
            return center

    def clamped(center: Point) -> Point:
        x = min(max(center[0], w / 2), iw - w / 2) if w <= iw else iw / 2
        y = min(max(center[1], h / 2), ih - h / 2) if h <= ih else ih / 2
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
