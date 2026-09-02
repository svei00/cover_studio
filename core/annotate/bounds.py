"""Cuanto se sale lo dibujado de los bordes de la imagen (el resplandor, las
flechas y las etiquetas pueden recortarse) y cuanto margen extra hace falta."""

from __future__ import annotations

import math
from collections.abc import Iterable

from core.annotate.model import Annotation, AnnotationDoc, Rect, TextLabel
from core.annotate.primitives import (
    PCircle,
    PEllipse,
    PImage,
    PLine,
    PPolygon,
    PRect,
    Primitive,
    doc_scale,
    item_primitives,
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
    if isinstance(p, PEllipse):
        box = Rect(p.center[0] - p.rx, p.center[1] - p.ry, 2 * p.rx, 2 * p.ry)
        return box.inflate(p.width / 2) if p.stroke else box
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


def item_box(doc: AnnotationDoc, item: Annotation, scale: float) -> Rect | None:
    """Caja que ocupa lo dibujado de UNA anotacion (resplandor y etiquetas incluidos);
    None si no dibuja nada (el pixelado vive en el bitmap)."""
    boxes = [b for p in item_primitives(doc, item, scale) if (b := primitive_bounds(p)) is not None]
    if isinstance(item, TextLabel):
        boxes.append(label_box(item, scale))
    return union_bounds(boxes)


def _drawn_boxes(doc: AnnotationDoc) -> list[tuple[Annotation, Rect]]:
    scale = doc_scale(doc)
    return [(i, b) for i in doc.items if (b := item_box(doc, i, scale)) is not None]


def content_bounds(doc: AnnotationDoc) -> Rect | None:
    """Caja que ocupa todo lo dibujado: primitivas mas las cajas de las etiquetas de texto."""
    return union_bounds(box for _item, box in _drawn_boxes(doc))


def items_outside_view(doc: AnnotationDoc) -> list[Annotation]:
    """Anotaciones que quedan por completo fuera del recorte (no se ven ni se exportan).
    Sin recorte no hay nada fuera. El pixelado no cuenta: solo cambia pixeles."""
    if doc.crop is None:
        return []
    return [item for item, box in _drawn_boxes(doc) if not box.intersects(doc.crop)]


def required_padding(doc: AnnotationDoc) -> int:
    """Px de margen que hacen falta alrededor de lo que se exporta (la imagen o su recorte)
    para que nada se recorte (0 si todo cabe). Es independiente del margen que ya tenga el
    documento. Con recorte, lo que queda del todo fuera de el no pide margen."""
    boxes = [box for _item, box in _drawn_boxes(doc) if doc.crop is None or box.intersects(doc.crop)]
    box = union_bounds(boxes)
    if box is None:
        return 0
    view = doc.view
    overflow = max(0.0, view.x - box.x, view.y - box.y, box.right - view.right, box.bottom - view.bottom)
    return math.ceil(overflow)
