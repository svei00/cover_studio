"""Alinear y distribuir (como Photoshop o Figma): dadas las cajas de varias anotaciones, cuanto hay que mover cada una.
Geometria pura, sin Qt.

- Alinear: por defecto contra la caja que envuelve a TODAS las seleccionadas; o contra una caja dada (la imagen), y entonces
  tambien sirve con una sola (centrar un icono, pegarlo al borde).
- Distribuir (3 o mas): deja el mismo hueco entre cajas vecinas; las dos de los extremos no se mueven."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from core.annotate.model import Rect

Delta = tuple[float, float]


class Align(str, Enum):
    LEFT = "left"          # bordes izquierdos en una misma vertical
    CENTER_H = "center_h"  # centros en una misma vertical (centrar horizontalmente)
    RIGHT = "right"
    TOP = "top"            # bordes de arriba en una misma horizontal
    MIDDLE_V = "middle_v"  # centros en una misma horizontal (centrar verticalmente)
    BOTTOM = "bottom"


class Distribute(str, Enum):
    HORIZONTAL = "horizontal"   # mismo hueco entre columnas
    VERTICAL = "vertical"       # mismo hueco entre filas


MIN_TO_DISTRIBUTE = 3


def bounds(boxes: Mapping[str, Rect]) -> Rect:
    """La caja que envuelve a todas."""
    x0 = min(b.x for b in boxes.values())
    y0 = min(b.y for b in boxes.values())
    x1 = max(b.right for b in boxes.values())
    y1 = max(b.bottom for b in boxes.values())
    return Rect(x0, y0, x1 - x0, y1 - y0)


def align_deltas(boxes: Mapping[str, Rect], mode: Align, reference: Rect | None = None) -> dict[str, Delta]:
    """Cuanto mover cada caja para alinearla (solo las que cambian). Sin `reference` se alinean contra la caja que las
    envuelve a todas y con menos de dos no hay nada que alinear; con `reference` (la imagen) cada una se alinea contra
    ESA caja por separado, tambien una sola."""
    if not boxes or (reference is None and len(boxes) < 2):
        return {}
    whole = reference if reference is not None else bounds(boxes)
    out: dict[str, Delta] = {}
    for key, b in boxes.items():
        if mode is Align.LEFT:
            delta = (whole.x - b.x, 0.0)
        elif mode is Align.RIGHT:
            delta = (whole.right - b.right, 0.0)
        elif mode is Align.CENTER_H:
            delta = (whole.center[0] - b.center[0], 0.0)
        elif mode is Align.TOP:
            delta = (0.0, whole.y - b.y)
        elif mode is Align.BOTTOM:
            delta = (0.0, whole.bottom - b.bottom)
        else:
            delta = (0.0, whole.center[1] - b.center[1])
        if abs(delta[0]) > 1e-9 or abs(delta[1]) > 1e-9:
            out[key] = delta
    return out


def distribute_deltas(boxes: Mapping[str, Rect], axis: Distribute) -> dict[str, Delta]:
    """Cuanto mover cada caja para que los huecos entre vecinas sean iguales. La primera y la ultima (por posicion) se
    quedan donde estan. Con menos de tres no hay nada que distribuir."""
    if len(boxes) < MIN_TO_DISTRIBUTE:
        return {}
    horizontal = axis is Distribute.HORIZONTAL
    start = (lambda b: b.x) if horizontal else (lambda b: b.y)
    size = (lambda b: b.w) if horizontal else (lambda b: b.h)
    ordered = sorted(boxes.items(), key=lambda kv: (start(kv[1]), kv[0]))   # por posicion; el id desempata
    first, last = ordered[0][1], ordered[-1][1]
    span = start(last) + size(last) - start(first)
    gap = (span - sum(size(b) for _k, b in ordered)) / (len(ordered) - 1)
    out: dict[str, Delta] = {}
    cursor = start(first)
    for key, b in ordered:
        move = cursor - start(b)
        if abs(move) > 1e-9:
            out[key] = (move, 0.0) if horizontal else (0.0, move)
        cursor += size(b) + gap
    return out
