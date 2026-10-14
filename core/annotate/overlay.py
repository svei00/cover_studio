"""Imagen pegada encima de la captura (Ctrl+Shift+V): geometria pura, sin Qt.

La imagen entra a su tamano REAL (1:1, lo mas nitido que hay) centrada en la parte visible de la captura; solo si no cabe
se reduce, siempre conservando la proporcion. Se redimensiona desde el ORIGINAL (nunca desde una copia ya reducida), asi
agrandar, reducir y volver a agrandar no degrada la imagen."""

from __future__ import annotations

from core.annotate.model import ImageOverlay, Rect

FIT_RATIO = 0.9   # una imagen que no cabe se reduce para ocupar, como mucho, este tanto de la parte visible


def initial_rect(size: tuple[int, int], view: Rect, fit: float = FIT_RATIO) -> Rect:
    """Donde y con que tamano entra una imagen recien pegada: a tamano real y centrada en `view`; si es mas grande que
    `fit` de la zona visible, se reduce (proporcional) hasta que quepa. Origen en pixeles enteros (1:1 sin remuestreo)."""
    width, height = float(size[0]), float(size[1])
    ratio = min(1.0, fit * view.w / width, fit * view.h / height)
    w, h = max(1, round(width * ratio)), max(1, round(height * ratio))
    cx, cy = view.center
    return Rect(round(cx - w / 2), round(cy - h / 2), w, h)


def real_size_rect(item: ImageOverlay) -> Rect:
    """La misma imagen a su tamano real (1:1), con el mismo centro."""
    w, h = item.size
    cx, cy = item.rect.center
    return Rect(round(cx - w / 2), round(cy - h / 2), w, h)


def scale_percent(item: ImageOverlay) -> float:
    """Cuanto mide ahora respecto a su tamano real (100 = 1:1)."""
    return 100.0 * item.rect.w / item.size[0] if item.size[0] else 100.0


def is_real_size(item: ImageOverlay) -> bool:
    return round(item.rect.w) == item.size[0] and round(item.rect.h) == item.size[1]
