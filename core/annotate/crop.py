"""Recorte no destructivo de la captura. Sin Qt. El recorte es un rectangulo en pixeles
de la imagen fuente: las anotaciones siguen en esas mismas coordenadas y solo cambia
la region que se muestra y se exporta."""

from __future__ import annotations

from core.annotate import edit
from core.annotate.model import Rect

Point = tuple[float, float]

MIN_CROP = 16.0   # lado minimo de un recorte, en pixeles de la imagen


def full_rect(image_size: tuple[int, int]) -> Rect:
    return Rect(0.0, 0.0, float(image_size[0]), float(image_size[1]))


def normalize_crop(rect: Rect | None, image_size: tuple[int, int]) -> Rect | None:
    """Recorte valido para `image_size` o None: se limita a la imagen, se redondea a
    pixeles enteros (el PNG exportado mide pixeles enteros) y se descarta si es muy
    pequeno o si cubre toda la imagen (eso es no tener recorte)."""
    if rect is None:
        return None
    width, height = image_size
    left = round(min(max(rect.x, 0.0), width))
    top = round(min(max(rect.y, 0.0), height))
    right = round(min(max(rect.right, 0.0), width))
    bottom = round(min(max(rect.bottom, 0.0), height))
    if right - left < MIN_CROP or bottom - top < MIN_CROP:
        return None
    if (left, top, right, bottom) == (0, 0, width, height):
        return None
    return Rect(float(left), float(top), float(right - left), float(bottom - top))


def crop_handles(rect: Rect) -> dict[edit.Handle, Point]:
    """Las 8 asas del rectangulo de recorte."""
    return edit.rect_handles(rect)


def hit_crop_handle(rect: Rect, p: Point, tol: float) -> edit.Handle | None:
    """Asa del recorte bajo el punto; si hay varias cerca gana la mas cercana."""
    best: tuple[float, edit.Handle] | None = None
    for handle, pos in crop_handles(rect).items():
        d = ((p[0] - pos[0]) ** 2 + (p[1] - pos[1]) ** 2) ** 0.5
        if d <= tol and (best is None or d < best[0]):
            best = (d, handle)
    return best[1] if best else None


def resize_crop(rect: Rect, handle: edit.Handle, p: Point) -> Rect:
    """Mueve el asa al punto sin bajar del lado minimo."""
    return edit.resize_rect(rect, handle, p, MIN_CROP)
