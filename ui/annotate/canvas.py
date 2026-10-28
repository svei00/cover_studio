"""Lienzo que muestra la captura con sus anotaciones y reenvia el mouse y el teclado al
EditController. Por defecto la captura se ajusta a la ventana; con la rueda se hace zoom hacia el
cursor y con el boton central (o Espacio + arrastrar) se desplaza. El zoom es solo de VISTA: no
cambia lo que se exporta."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QMenu, QSizePolicy, QWidget

from core.annotate import crop as cropping
from core.annotate import edit
from core.annotate.model import Arrow, Rect
from core.annotate.primitives import Primitive
from core.annotate.style import CARD_FILL
from ui.annotate.context_menu import build_context_menu
from ui.annotate.controller import EditController, Tool
from ui.annotate.painter import paint_primitives

MARGIN = 12
MAX_ZOOM = 2.0          # tope del ajuste automatico (una captura chica no se agranda mas de 2x)
MAX_VIEW_ZOOM = 32.0    # tope del zoom manual
WHEEL_STEP = 1.2        # factor por cada "clic" de la rueda
ZOOM_BUTTON_STEP = 1.25
FIT_SNAP = 1.01         # un zoom manual a menos de 1 % del ajuste vuelve al modo "Ajustar"
SMOOTH_UP_TO = 2.0      # arriba de esta escala se muestran los pixeles sin suavizar (para ubicar con precision)
TOLERANCE_PX = 8.0  # tolerancia de clic en pixeles de pantalla
HANDLE_PX = 9.0
SELECTION_COLOR = "#4DA3FF"
CROP_DIM = QColor(0, 0, 0, 150)
NUDGE = 1.0
NUDGE_BIG = 10.0
HINT = "Arrastra una captura aqui, usa Abrir... o presiona CTRL + V"


class AnnotateCanvas(QWidget):
    zoomChanged = Signal(float)   # escala de la vista (1.0 = 100 %)

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
        # zoom manual: None = "Ajustar". `_center` es el punto de la imagen que queda en el centro
        # de la vista; asi un cambio de tamano de la ventana o del recorte no mueve lo que se mira.
        self._zoom: float | None = None
        self._center: tuple[float, float] = (0.0, 0.0)
        self._pan_last: QPointF | None = None
        self._space_down = False
        self._last_scale = 0.0

    def set_controller(self, controller: EditController) -> None:
        self._controller = controller
        controller.selectionChanged.connect(self.update)
        controller.toolChanged.connect(self._on_tool_changed)
        controller.cropDraftChanged.connect(self.update)
        controller.marqueeChanged.connect(self.update)

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
        self._notify_zoom()
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

    def _fit_scale(self) -> float:
        """Escala que ajusta todo lo que se muestra (con su margen extra) a la ventana."""
        _fx, _fy, fw, fh, pad = self._frame()
        content_w = fw + 2 * pad  # el margen extra tambien se ve
        content_h = fh + 2 * pad
        avail_w = max(1, self.width() - 2 * MARGIN)
        avail_h = max(1, self.height() - 2 * MARGIN)
        return min(MAX_ZOOM, avail_w / content_w, avail_h / content_h)

    def _clamp_center(self, center: tuple[float, float], scale: float) -> tuple[float, float]:
        """Mantiene la imagen a la vista: si cabe en la ventana se centra; si no, se puede
        desplazar hasta que su borde llegue al margen."""
        fx, fy, fw, fh, pad = self._frame()
        out = []
        for c, f, length, view in ((center[0], fx, fw, self.width()), (center[1], fy, fh, self.height())):
            low, high = f - pad, f + length + pad
            half = view / (2 * scale)
            if high - low <= 2 * half:
                out.append((low + high) / 2)
            else:
                m = MARGIN / scale
                out.append(min(max(c, low + half - m), high - half + m))
        return out[0], out[1]

    def view_layout(self) -> tuple[float, float, float]:
        """(escala, offset_x, offset_y) de la vista. Sin zoom manual ajusta la imagen a la ventana,
        centrada; con zoom, la escala es la elegida y `_center` queda en el centro de la ventana."""
        if not self.has_image():
            return 1.0, 0.0, 0.0
        fx, fy, fw, fh, pad = self._frame()
        if self._zoom is None:
            scale = self._fit_scale()
            center = (fx + fw / 2, fy + fh / 2)
        else:
            scale = self._zoom
            center = self._clamp_center(self._center, scale)
        ox = self.width() / 2 - (center[0] - fx + pad) * scale
        oy = self.height() / 2 - (center[1] - fy + pad) * scale
        return scale, ox, oy

    def view_to_image(self, pos: QPointF) -> tuple[float, float]:
        scale, ox, oy = self.view_layout()
        fx, fy, _fw, _fh, pad = self._frame()
        return (pos.x() - ox) / scale - pad + fx, (pos.y() - oy) / scale - pad + fy

    def image_to_view(self, point: tuple[float, float]) -> QPointF:
        scale, ox, oy = self.view_layout()
        fx, fy, _fw, _fh, pad = self._frame()
        return QPointF(ox + (point[0] - fx + pad) * scale, oy + (point[1] - fy + pad) * scale)

    # ------------------------------------------------------------------
    # Zoom y desplazamiento (solo de vista)
    # ------------------------------------------------------------------

    def zoom_scale(self) -> float:
        """Escala actual de la vista (1.0 = 100 %)."""
        return self.view_layout()[0]

    def is_fitted(self) -> bool:
        return self._zoom is None

    def _notify_zoom(self) -> None:
        scale = self.zoom_scale()
        if abs(scale - self._last_scale) > 1e-9:
            self._last_scale = scale
            self.zoomChanged.emit(scale)

    def _set_view(self, zoom: float | None, center: tuple[float, float] | None = None) -> None:
        if not self.has_image():
            return
        if zoom is None:
            self._zoom = None
        else:
            zoom = min(max(zoom, 0.01), MAX_VIEW_ZOOM)
            if center is not None:
                self._center = center
            self._center = self._clamp_center(self._center, zoom)
            self._zoom = zoom
        self._notify_zoom()
        self.update()

    def _view_center_in_image(self) -> tuple[float, float]:
        return self.view_to_image(QPointF(self.width() / 2, self.height() / 2))

    def fit(self) -> None:
        """Ajusta la captura a la ventana."""
        self._set_view(None)

    def actual_size(self) -> None:
        """100 %: un pixel de la imagen por pixel de pantalla, sobre lo que se estaba mirando."""
        self._set_view(1.0, self._view_center_in_image())

    def reset_view(self) -> None:
        """Vista nueva (otra captura): ajustada."""
        self._zoom = None
        self._last_scale = 0.0
        self._notify_zoom()

    def zoom_at(self, factor: float, view_pos: QPointF | None = None) -> None:
        """Multiplica el zoom por `factor` dejando quieto el punto de la imagen que esta bajo
        `view_pos` (el centro de la ventana si no se da). Nunca baja del ajuste."""
        if not self.has_image():
            return
        pos = view_pos if view_pos is not None else QPointF(self.width() / 2, self.height() / 2)
        scale = self.zoom_scale()
        fit = self._fit_scale()
        new = min(max(scale * factor, fit), MAX_VIEW_ZOOM)
        if abs(new - scale) < 1e-9:
            return
        if new <= fit * FIT_SNAP:
            self._set_view(None)
            return
        anchor = self.view_to_image(pos)
        fx, fy, _fw, _fh, pad = self._frame()
        ox = pos.x() - (anchor[0] - fx + pad) * new
        oy = pos.y() - (anchor[1] - fy + pad) * new
        center = (fx - pad + (self.width() / 2 - ox) / new, fy - pad + (self.height() / 2 - oy) / new)
        self._set_view(new, center)

    def pan_by(self, dx: float, dy: float) -> None:
        """Desplaza la vista dx, dy pixeles de pantalla (el contenido sigue al mouse)."""
        scale = self.zoom_scale()
        cx, cy = self._view_center_in_image()
        self._set_view(scale, (cx - dx / scale, cy - dy / scale))

    def _on_tool_changed(self, _tool) -> None:
        self._notify_zoom()   # Recortar muestra la imagen completa: cambia la escala del ajuste
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._notify_zoom()

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
        scale, ox, oy = self.view_layout()
        hints = QPainter.Antialiasing | QPainter.TextAntialiasing
        if scale <= SMOOTH_UP_TO:
            hints |= QPainter.SmoothPixmapTransform
        painter.setRenderHints(hints)   # con mucho zoom se ven los pixeles tal cual, para ubicar con precision
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
        self._paint_marquee(painter)

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
        items = self._controller.selected_items()
        if len(items) >= 2:
            self._paint_multi_selection(painter, items)
            return
        item = self._controller.selected_item()
        if item is None:
            return
        handles = edit.item_handles(item, self._controller.marker_arrows())
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
        for handle, point in handles.items():
            c = self.image_to_view(point)
            box = QRectF(c.x() - half, c.y() - half, HANDLE_PX, HANDLE_PX)
            if handle in (edit.Handle.CONN_START, edit.Handle.CONN_END, edit.Handle.MID):   # los del conector y el de la Z son redondos y de otro color
                painter.setBrush(QColor(SELECTION_COLOR))
                painter.drawEllipse(box)
                painter.setBrush(QColor("#FFFFFF"))
            else:
                painter.drawRect(box)

    def _paint_multi_selection(self, painter: QPainter, items: Sequence) -> None:
        """Varias seleccionadas: la caja punteada de cada una y, alrededor de todas, la caja del conjunto (a la que se
        alinean). Sin asas: lo que se puede hacer con varias es moverlas, alinearlas y borrarlas."""
        assert self._controller is not None
        scale = self._controller.scale()
        boxes = [box for item in items for box in edit.selection_rects(item, scale)]
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(SELECTION_COLOR), 1.5, Qt.DashLine))
        for box in boxes:
            painter.drawRect(QRectF(self.image_to_view((box.x, box.y)), self.image_to_view((box.right, box.bottom))).adjusted(-3, -3, 3, 3))
        left, top = min(b.x for b in boxes), min(b.y for b in boxes)
        right, bottom = max(b.right for b in boxes), max(b.bottom for b in boxes)
        painter.setPen(QPen(QColor(SELECTION_COLOR), 1.0))
        painter.drawRect(QRectF(self.image_to_view((left, top)), self.image_to_view((right, bottom))).adjusted(-7, -7, 7, 7))

    def _paint_marquee(self, painter: QPainter) -> None:
        """El rectangulo que se arrastra sobre un hueco para seleccionar lo que toca."""
        if self._controller is None or self._controller.marquee is None:
            return
        box = self._controller.marquee
        rect = QRectF(self.image_to_view((box.x, box.y)), self.image_to_view((box.right, box.bottom)))
        painter.setPen(QPen(QColor(SELECTION_COLOR), 1.0))
        painter.setBrush(QColor(77, 163, 255, 40))
        painter.drawRect(rect)

    # ------------------------------------------------------------------
    # Mouse y teclado
    # ------------------------------------------------------------------

    def _panning_button(self, event: QMouseEvent) -> bool:
        return event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_down)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self.has_image() and self._panning_button(event):
            self.setFocus()
            self._pan_last = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton or self._controller is None or not self.has_image():
            return
        self.setFocus()
        additive = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))   # suma o quita de la seleccion
        self._controller.press(self.view_to_image(event.position()), self._tolerance(), additive)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 (Qt override)
        """Clic derecho sobre una anotacion: la selecciona (si no lo estaba) y abre su menu. En un hueco no hay menu."""
        if self._controller is None or not self.has_image():
            return
        point = self.view_to_image(QPointF(event.pos()))
        if not self._controller.select_for_context_menu(point, self._tolerance()):
            return
        menu = build_context_menu(self._controller, self)
        if menu is not None:
            self._exec_menu(menu, event.globalPos())
        event.accept()

    def _exec_menu(self, menu: QMenu, global_pos: QPoint) -> None:
        """Abre el menu y espera a que se elija algo. Aparte para que las pruebas lo sustituyan: un menu real es modal."""
        menu.exec(global_pos)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.pan_by(delta.x(), delta.y())
            return
        if self._controller is None or not self.has_image():
            return
        point = self.view_to_image(event.position())
        if event.buttons() & Qt.LeftButton:
            self._controller.free_resize = bool(event.modifiers() & Qt.ShiftModifier)   # imagen pegada: estirar libre
            self._controller.move(point)
        else:
            self.setCursor(self._controller.cursor_at(point, self._tolerance()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._pan_last is not None and (event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton):
            self._pan_last = None
            self.setCursor(Qt.OpenHandCursor if self._space_down else Qt.ArrowCursor)
            return
        if event.button() != Qt.LeftButton or self._controller is None or not self.has_image():
            return
        point = self.view_to_image(event.position())
        self._controller.release(point)
        self.setCursor(self._controller.cursor_at(point, self._tolerance()))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt override)
        """Rueda = zoom hacia el cursor; el desplazamiento horizontal del touchpad mueve la vista."""
        if not self.has_image():
            return
        delta = event.angleDelta()
        if delta.y():
            self.zoom_at(WHEEL_STEP ** (delta.y() / 120), event.position())
        if delta.x():
            self.pan_by(delta.x() / 4, 0.0)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if self._pan_last is None:
                self.unsetCursor()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._space_down = False
        self._pan_last = None
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        c = self._controller
        if c is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Space:
            if not event.isAutoRepeat():
                self._space_down = True
                self.setCursor(Qt.OpenHandCursor)
            return
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
