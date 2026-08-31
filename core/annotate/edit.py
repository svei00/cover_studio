"""Logica pura de edicion: hit-testing, asas de redimensionado, mover y
redimensionar. Sin Qt, para poder testear la interaccion sin ventana. Todas las
coordenadas estan en pixeles de la imagen fuente; `tol` es la tolerancia de
clic ya convertida a esos pixeles."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import replace
from enum import Enum

from core.annotate import style
from core.annotate.model import (
    Annotation,
    Arrow,
    Marker,
    Rect,
    Redaction,
    StepBadge,
    TextLabel,
)
from core.annotate.primitives import label_box

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

def hit_item(item: Annotation, p: Point, tol: float, scale: float) -> bool:
    if isinstance(item, Marker):
        outer = item.rect.inflate(tol)
        inner = item.rect.inflate(-tol)
        if item.rect.w <= 2 * tol or item.rect.h <= 2 * tol:
            return _contains(outer, p)
        return _contains(outer, p) and not _contains(inner, p)
    if isinstance(item, Redaction):
        return _contains(item.rect.inflate(tol), p)
    if isinstance(item, Arrow):
        return distance_to_segment(p, item.start, item.end) <= tol
    if isinstance(item, StepBadge):
        return math.hypot(p[0] - item.center[0], p[1] - item.center[1]) <= style.STEP_RADIUS * scale + tol / 2
    if isinstance(item, TextLabel):
        return _contains(label_box(item, scale).inflate(tol / 2), p)
    return False


def hit_test(items: Sequence[Annotation], p: Point, tol: float, scale: float) -> str | None:
    """Id de la anotacion mas arriba (la ultima dibujada) bajo el punto."""
    for item in reversed(items):
        if hit_item(item, p, tol, scale):
            return item.id
    return None


def item_handles(item: Annotation) -> dict[Handle, Point]:
    """Asas de redimensionado: 8 para rectangulos, 2 para flechas, ninguna para el resto."""
    if isinstance(item, (Marker, Redaction)):
        r = item.rect
        cx, cy = r.center
        return {
            Handle.NW: (r.x, r.y), Handle.N: (cx, r.y), Handle.NE: (r.right, r.y),
            Handle.E: (r.right, cy), Handle.SE: (r.right, r.bottom), Handle.S: (cx, r.bottom),
            Handle.SW: (r.x, r.bottom), Handle.W: (r.x, cy),
        }
    if isinstance(item, Arrow):
        return {Handle.START: item.start, Handle.END: item.end}
    return {}


def hit_handle(item: Annotation, p: Point, tol: float) -> Handle | None:
    """Asa bajo el punto; si hay varias cerca gana la mas cercana."""
    best: tuple[float, Handle] | None = None
    for handle, pos in item_handles(item).items():
        d = math.hypot(p[0] - pos[0], p[1] - pos[1])
        if d <= tol and (best is None or d < best[0]):
            best = (d, handle)
    return best[1] if best else None


def selection_rect(item: Annotation, scale: float) -> Rect:
    """Caja que se dibuja alrededor de la anotacion seleccionada."""
    if isinstance(item, (Marker, Redaction)):
        return item.rect
    if isinstance(item, Arrow):
        x0, x1 = sorted((item.start[0], item.end[0]))
        y0, y1 = sorted((item.start[1], item.end[1]))
        return Rect(x0, y0, x1 - x0, y1 - y0)
    if isinstance(item, StepBadge):
        r = style.STEP_RADIUS * scale
        return Rect(item.center[0] - r, item.center[1] - r, 2 * r, 2 * r)
    return label_box(item, scale)


# --------------------------------------------------------------------------
# Mover y redimensionar (devuelven una anotacion nueva; las originales son inmutables)
# --------------------------------------------------------------------------

def move_item(item: Annotation, dx: float, dy: float) -> Annotation:
    if isinstance(item, (Marker, Redaction)):
        r = item.rect
        return replace(item, rect=Rect(r.x + dx, r.y + dy, r.w, r.h))
    if isinstance(item, Arrow):
        return replace(
            item,
            start=(item.start[0] + dx, item.start[1] + dy),
            end=(item.end[0] + dx, item.end[1] + dy),
        )
    if isinstance(item, StepBadge):
        return replace(item, center=(item.center[0] + dx, item.center[1] + dy))
    if isinstance(item, TextLabel):
        return replace(item, pos=(item.pos[0] + dx, item.pos[1] + dy))
    return item


def resize_item(item: Annotation, handle: Handle, p: Point, min_size: float = 4.0) -> Annotation:
    """Mueve el asa al punto. Los rectangulos nunca bajan de min_size; si se
    arrastra el asa mas alla del lado opuesto, se queda en min_size."""
    if isinstance(item, Arrow):
        if handle is Handle.START:
            return replace(item, start=p)
        if handle is Handle.END:
            return replace(item, end=p)
        return item
    if not isinstance(item, (Marker, Redaction)):
        return item

    r = item.rect
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
    return replace(item, rect=Rect(left, top, right - left, bottom - top))


def rect_from_points(a: Point, b: Point) -> Rect:
    """Rectangulo normalizado entre dos esquinas cualesquiera."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    return Rect(x0, y0, x1 - x0, y1 - y0)
