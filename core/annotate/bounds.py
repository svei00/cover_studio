"""Cuanto se sale lo dibujado de los bordes de la imagen (el resplandor, las
flechas y las etiquetas pueden recortarse) y cuanto margen extra hace falta."""

from __future__ import annotations

import math
from collections.abc import Iterable

from core.annotate.model import AnnotationDoc, Rect, TextLabel
from core.annotate.primitives import (
    PCircle,
    PImage,
    PLine,
    PPolygon,
    PRect,
    Primitive,
    build_primitives,
    doc_scale,
    label_box,
)


def primitive_bounds(p: Primitive) -> Rect | None:
    """Caja que ocupa una primitiva incluyendo el grosor de su trazo (el texto no cuenta)."""
    if isinstance(p, PRect):
        return p.rect.inflate(p.width / 2) if p.stroke else p.rect
    if isinstance(p, PLine):
        xs, ys = (p.a[0], p.b[0]), (p.a[1], p.b[1])
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).inflate(p.width / 2)
    if isinstance(p, PPolygon):
        xs, ys = [x for x, _ in p.points], [y for _, y in p.points]
        box = Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        return box.inflate(p.width / 2) if p.stroke else box
    if isinstance(p, PCircle):
        r = p.r + (p.width / 2 if p.stroke else 0.0)
        return Rect(p.center[0] - r, p.center[1] - r, 2 * r, 2 * r)
    if isinstance(p, PImage):
        return p.dest
    return None


def union_bounds(boxes: Iterable[Rect]) -> Rect | None:
    boxes = list(boxes)
    if not boxes:
        return None
    x0 = min(b.x for b in boxes)
    y0 = min(b.y for b in boxes)
    x1 = max(b.right for b in boxes)
    y1 = max(b.bottom for b in boxes)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def content_bounds(doc: AnnotationDoc) -> Rect | None:
    """Caja que ocupa todo lo dibujado: primitivas mas las cajas de las etiquetas de texto."""
    scale = doc_scale(doc)
    boxes = [b for p in build_primitives(doc) if (b := primitive_bounds(p)) is not None]
    boxes += [label_box(i, scale) for i in doc.items if isinstance(i, TextLabel)]
    return union_bounds(boxes)


def required_padding(doc: AnnotationDoc) -> int:
    """Px de margen que hacen falta alrededor de la imagen para que nada se recorte
    (0 si todo cabe). Es independiente del margen que ya tenga el documento."""
    box = content_bounds(doc)
    if box is None:
        return 0
    width, height = doc.image_size
    overflow = max(0.0, -box.x, -box.y, box.right - width, box.bottom - height)
    return math.ceil(overflow)
