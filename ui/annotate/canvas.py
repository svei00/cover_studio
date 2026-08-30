"""Lienzo que muestra la captura con sus anotaciones, ajustada a la ventana."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.annotate.primitives import Primitive
from ui.annotate.painter import paint_primitives

MARGIN = 12
MAX_ZOOM = 2.0
HINT = "Arrastra una captura aqui, usa Abrir... o presiona CTRL + V"


class AnnotateCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image: QImage | None = None
        self._primitives: list[Primitive] = []

    def set_content(self, image: QImage | None, primitives: Sequence[Primitive]) -> None:
        self._image = image
        self._primitives = list(primitives)
        self.update()

    def view_layout(self) -> tuple[float, float, float]:
        """(escala, offset_x, offset_y) que ajustan la imagen al widget, centrada."""
        if self._image is None or self._image.isNull():
            return 1.0, 0.0, 0.0
        avail_w = max(1, self.width() - 2 * MARGIN)
        avail_h = max(1, self.height() - 2 * MARGIN)
        scale = min(MAX_ZOOM, avail_w / self._image.width(), avail_h / self._image.height())
        ox = (self.width() - self._image.width() * scale) / 2
        oy = (self.height() - self._image.height() * scale) / 2
        return scale, ox, oy

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202020"))
        if self._image is None or self._image.isNull():
            painter.setPen(QColor("#AAAAAA"))
            painter.drawText(self.rect(), Qt.AlignCenter, HINT)
            return
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        scale, ox, oy = self.view_layout()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        painter.drawImage(0, 0, self._image)
        paint_primitives(painter, self._primitives)
