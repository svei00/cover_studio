"""Lienzo que muestra la captura con sus anotaciones, ajustada a la ventana, y
reenvia el mouse y el teclado al EditController."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.annotate import crop as cropping
from core.annotate import edit
from core.annotate.model import Arrow, Rect
from core.annotate.primitives import Primitive
from core.annotate.style import CARD_FILL
from ui.annotate.controller import EditController, Tool
from ui.annotate.painter import paint_primitives

MARGIN = 12
MAX_ZOOM = 2.0
TOLERANCE_PX = 8.0  # tolerancia de clic en pixeles de pantalla
HANDLE_PX = 9.0
SELECTION_COLOR = "#4DA3FF"
CROP_DIM = QColor(0, 0, 0, 150)
NUDGE = 1.0
NUDGE_BIG = 10.0
HINT = "Arrastra una captura aqui, usa Abrir... o presiona CTRL + V"


class AnnotateCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._image: QImage | None = None
        self._primitives: list[Primitive] = []
        self._lens_images: Mapping[str, QImage] = {}
        self._padding = 0
        self._crop: Rect | None = None
        self._controller: EditController | None = None

    def set_controller(self, controller: EditController) -> None:
        self._controller = controller
        controller.selectionChanged.connect(self.update)
        controller.toolChanged.connect(lambda _tool: self.update())
        controller.cropDraftChanged.connect(self.update)

    def set_content(
        self,
        image: QImage | None,
        primitives: Sequence[Primitive],
        lens_images: Mapping[str, QImage] | None = None,
        padding: int = 0,
        crop: Rect | None = None,
    ) -> None:
        self._image = image
        self._crop = crop
        self._primitives = list(primitives)
        self._lens_images = lens_images or {}
        self._padding = max(0, padding)
        self.update()

    # ------------------------------------------------------------------
    # Vista
    # ------------------------------------------------------------------

    def has_image(self) -> bool:
        return self._image is not None and not self._image.isNull()

    def _editing_crop(self) -> bool:
        return self._controller is not None and self._controller.tool is Tool.CROP

    def _frame(self) -> tuple[float, float, float, float, int]:
        """(x, y, ancho, alto, margen): la region de la imagen que se muestra. Es el recorte
        (o todo) y su margen extra; con la herramienta Recortar se ve la imagen completa para
        poder agrandar o mover el recorte."""
        assert self._image is not None
        full = (0.0, 0.0, float(self._image.width()), float(self._image.height()))
        if self._editing_crop():
            return (*full, 0)
        if self._crop is not None:
            return self._crop.x, self._crop.y, self._crop.w, self._crop.h, self._padding
        return (*full, self._padding)

    def view_layout(self) -> tuple[float, float, float]:
        """(escala, offset_x, offset_y) que ajustan la imagen al widget, centrada."""
        if not self.has_image():
            return 1.0, 0.0, 0.0
        _fx, _fy, fw, fh, pad = self._frame()
        content_w = fw + 2 * pad  # el margen extra tambien se ve
        content_h = fh + 2 * pad
        avail_w = max(1, self.width() - 2 * MARGIN)
        avail_h = max(1, self.height() - 2 * MARGIN)
        scale = min(MAX_ZOOM, avail_w / content_w, avail_h / content_h)
        ox = (self.width() - content_w * scale) / 2
        oy = (self.height() - content_h * scale) / 2
        return scale, ox, oy

    def view_to_image(self, pos: QPointF) -> tuple[float, float]:
        scale, ox, oy = self.view_layout()
        fx, fy, _fw, _fh, pad = self._frame()
        return (pos.x() - ox) / scale - pad + fx, (pos.y() - oy) / scale - pad + fy

    def image_to_view(self, point: tuple[float, float]) -> QPointF:
        scale, ox, oy = self.view_layout()
        fx, fy, _fw, _fh, pad = self._frame()
        return QPointF(ox + (point[0] - fx + pad) * scale, oy + (point[1] - fy + pad) * scale)

    def _tolerance(self) -> float:
        """Tolerancia de clic convertida a pixeles de imagen."""
        return TOLERANCE_PX / self.view_layout()[0]

    # ------------------------------------------------------------------
    # Pintado
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202020"))
        if not self.has_image():
            painter.setPen(QColor("#AAAAAA"))
            painter.drawText(self.rect(), Qt.AlignCenter, HINT)
            return
        assert self._image is not None
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        scale, ox, oy = self.view_layout()
        painter.save()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        fx, fy, fw, fh, pad = self._frame()
        total_w = fw + 2 * pad
        total_h = fh + 2 * pad
        # solo se ve lo que se exportaria: lo que se sale de la region mostrada mas su margen se recorta
        painter.setClipRect(QRectF(0, 0, total_w, total_h))
        if pad:
            painter.fillRect(QRectF(0, 0, total_w, total_h), QColor(CARD_FILL))
        painter.translate(pad - fx, pad - fy)
        painter.save()
        painter.setClipRect(QRectF(fx, fy, fw, fh), Qt.IntersectClip)
        painter.drawImage(0, 0, self._image)
        painter.restore()
        paint_primitives(painter, self._primitives, self._lens_images)
        painter.restore()
        if self._editing_crop():
            self._paint_crop_overlay(painter)
        self._paint_selection(painter)

    def _paint_crop_overlay(self, painter: QPainter) -> None:
        """Con la herramienta Recortar: oscurece lo que quedaria fuera y dibuja las asas."""
        if self._controller is None:
            return
        rect = self._controller.crop_rect()
        assert self._image is not None
        if rect is None:
            return
        full = QRectF(self.image_to_view((0.0, 0.0)), self.image_to_view((self._image.width(), self._image.height())))
        inner = QRectF(self.image_to_view((rect.x, rect.y)), self.image_to_view((rect.right, rect.bottom)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(CROP_DIM)
        painter.drawRect(QRectF(full.left(), full.top(), full.width(), inner.top() - full.top()))
        painter.drawRect(QRectF(full.left(), inner.bottom(), full.width(), full.bottom() - inner.bottom()))
        painter.drawRect(QRectF(full.left(), inner.top(), inner.left() - full.left(), inner.height()))
        painter.drawRect(QRectF(inner.right(), inner.top(), full.right() - inner.right(), inner.height()))
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(inner)
        painter.setPen(QPen(QColor(CARD_FILL), 1.5))
        painter.setBrush(QColor("#FFFFFF"))
        half = HANDLE_PX / 2
        for point in cropping.crop_handles(rect).values():
            c = self.image_to_view(point)
            painter.drawRect(QRectF(c.x() - half, c.y() - half, HANDLE_PX, HANDLE_PX))

    def _paint_selection(self, painter: QPainter) -> None:
        """Caja y asas de la anotacion seleccionada, en pixeles de pantalla (no
        forman parte de la imagen exportada)."""
        if self._controller is None:
            return
        item = self._controller.selected_item()
        if item is None:
            return
        handles = edit.item_handles(item)
        if not isinstance(item, Arrow):
            pen = QPen(QColor(SELECTION_COLOR), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for box in edit.selection_rects(item, self._controller.scale()):
                top_left = self.image_to_view((box.x, box.y))
                bottom_right = self.image_to_view((box.right, box.bottom))
                painter.drawRect(QRectF(top_left, bottom_right).adjusted(-4, -4, 4, 4))
        painter.setPen(QPen(QColor(CARD_FILL), 1.5))
        painter.setBrush(QColor("#FFFFFF"))
        half = HANDLE_PX / 2
        for point in handles.values():
            c = self.image_to_view(point)
            painter.drawRect(QRectF(c.x() - half, c.y() - half, HANDLE_PX, HANDLE_PX))

    # ------------------------------------------------------------------
    # Mouse y teclado
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.LeftButton or self._controller is None or not self.has_image():
            return
        self.setFocus()
        self._controller.press(self.view_to_image(event.position()), self._tolerance())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._controller is None or not self.has_image():
            return
        point = self.view_to_image(event.position())
        if event.buttons() & Qt.LeftButton:
            self._controller.move(point)
        else:
            self.setCursor(self._controller.cursor_at(point, self._tolerance()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.LeftButton or self._controller is None or not self.has_image():
            return
        point = self.view_to_image(event.position())
        self._controller.release(point)
        self.setCursor(self._controller.cursor_at(point, self._tolerance()))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        c = self._controller
        if c is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        step = NUDGE_BIG if event.modifiers() & Qt.ShiftModifier else NUDGE
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            c.delete_selected()
        elif key == Qt.Key_Escape:
            c.cancel()
        elif key == Qt.Key_Left:
            c.nudge(-step, 0.0)
        elif key == Qt.Key_Right:
            c.nudge(step, 0.0)
        elif key == Qt.Key_Up:
            c.nudge(0.0, -step)
        elif key == Qt.Key_Down:
            c.nudge(0.0, step)
        else:
            super().keyPressEvent(event)
