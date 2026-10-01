"""Panel de vista previa: renderiza en un QThreadPool para no congelar la UI
y permite arrastrar la banda con el mouse para reposicionarla."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from core.geometry import (
    BandGeometry,
    CanvasSize,
    CoverConfig,
    GeometryError,
    SubtitleLayout,
    build_svg,
    compute_band_geometry,
    render_png_bytes,
)


class _RenderSignals(QObject):
    finished = Signal(bytes, object, object)  # png bytes, BandGeometry y rect del subtitulo (o None), en px del lienzo
    failed = Signal(str)


class _RenderTask(QRunnable):
    """Genera el SVG y lo rasteriza a la resolucion de la vista previa, en
    un hilo aparte. compute_band_geometry es barato, asi que va aqui mismo
    para no tener que recalcularlo despues en el hilo principal."""

    def __init__(
        self,
        config: CoverConfig,
        lines: list[str],
        font_size: float,
        photo_path: Path | None,
        preview_width: int,
        subtitle: SubtitleLayout | None = None,
    ) -> None:
        super().__init__()
        self.signals = _RenderSignals()
        self._config = config
        self._lines = lines
        self._font_size = font_size
        self._photo_path = photo_path
        self._preview_width = preview_width
        self._subtitle = subtitle

    def run(self) -> None:
        try:
            scale = self._preview_width / self._config.canvas.width
            preview_height = max(1, round(self._config.canvas.height * scale))
            svg_text = build_svg(self._config, self._lines, self._font_size, self._photo_path, self._subtitle)
            png_bytes = render_png_bytes(svg_text, self._preview_width, preview_height)
        except GeometryError as exc:
            self.signals.failed.emit(str(exc))
            return
        band = compute_band_geometry(self._config)
        self.signals.finished.emit(png_bytes, band, self._subtitle.rect if self._subtitle else None)


class PreviewWidget(QLabel):
    """Muestra la portada renderizada y deja arrastrar con el mouse la banda (band_margin_left /
    band_margin_top) y el subtitulo (su esquina superior izquierda). El subtitulo va dibujado encima:
    si se solapan, gana."""

    PREVIEW_WIDTH = 800

    bandRepositioned = Signal(float, float)  # nuevo margin_left, margin_top (px reales del lienzo)
    subtitleRepositioned = Signal(float, float)  # nueva esquina superior izquierda del subtitulo (px del lienzo)
    renderFailed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(400, 225)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #202020; color: #AAAAAA;")
        self.setText("Genera una portada para verla aqui.")
        self.setMouseTracking(True)

        self._thread_pool = QThreadPool(self)
        self._canvas_size = CanvasSize(1920, 1080)
        self._band_rect: BandGeometry | None = None
        self._subtitle_rect: BandGeometry | None = None
        self._drag_target: str | None = None   # "band" o "subtitle"
        self._source_pixmap: QPixmap | None = None
        self._scale = 1.0  # px reales del lienzo -> px del widget
        self._offset = (0.0, 0.0)
        self._dragging = False
        self._drag_grab_offset = (0.0, 0.0)
        self._render_in_flight = False
        self._pending_request: dict | None = None
        self._discard_in_flight = False   # clear_preview con un render en curso: su resultado ya no sirve

    def clear_preview(self) -> None:
        """Vuelve al estado de recien abierto: sin imagen, sin banda ni subtitulo que arrastrar, y sin renders
        pendientes. Si ya hay uno corriendo, su resultado se descarta cuando termine (si no, repondria la portada vieja)."""
        self._pending_request = None
        self._discard_in_flight = self._render_in_flight
        self._source_pixmap = None
        self._band_rect = self._subtitle_rect = None
        self._dragging = False
        self._drag_target = None
        self.setPixmap(QPixmap())
        self.setText("Genera una portada para verla aqui.")
        self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------
    # Render en segundo plano
    # ------------------------------------------------------------------

    def request_render(
        self,
        config: CoverConfig,
        lines: list[str],
        font_size: float,
        photo_path: Path | None,
        subtitle: SubtitleLayout | None = None,
    ) -> None:
        """Encola un render. Si ya hay uno corriendo, este pedido reemplaza
        al pendiente anterior (solo interesa el mas reciente)."""
        self._canvas_size = config.canvas
        request = {
            "config": config, "lines": lines, "font_size": font_size, "photo_path": photo_path, "subtitle": subtitle,
        }
        if self._render_in_flight:
            self._pending_request = request
            return
        self._start_render(request)

    def _start_render(self, request: dict) -> None:
        self._render_in_flight = True
        task = _RenderTask(
            request["config"], request["lines"], request["font_size"], request["photo_path"], self.PREVIEW_WIDTH,
            request["subtitle"],
        )
        task.signals.finished.connect(self._on_render_finished)
        task.signals.failed.connect(self._on_render_failed)
        self._thread_pool.start(task)

    def _on_render_finished(self, png_bytes: bytes, band: BandGeometry, subtitle: BandGeometry | None = None) -> None:
        self._render_in_flight = False
        if self._discard_in_flight:
            self._discard_in_flight = False
            self._advance_queue()
            return
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")
        self._band_rect = band
        self._subtitle_rect = subtitle
        self._source_pixmap = pixmap
        self._redraw()
        self._advance_queue()

    def _on_render_failed(self, message: str) -> None:
        self._render_in_flight = False
        if self._discard_in_flight:
            self._discard_in_flight = False
            self._advance_queue()
            return
        self.renderFailed.emit(message)
        self._advance_queue()

    def _advance_queue(self) -> None:
        if self._pending_request is not None:
            next_request, self._pending_request = self._pending_request, None
            self._start_render(next_request)

    # ------------------------------------------------------------------
    # Dibujo y transformacion de coordenadas
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        if self._source_pixmap is None or self._source_pixmap.isNull():
            return
        scaled = self._source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)
        self._offset = ((self.width() - scaled.width()) / 2, (self.height() - scaled.height()) / 2)
        self._scale = scaled.width() / self._canvas_size.width if self._canvas_size.width else 1.0

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._redraw()

    def _widget_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        off_x, off_y = self._offset
        scale = self._scale or 1.0
        return (x - off_x) / scale, (y - off_y) / scale

    def _rect_widget(self, rect: BandGeometry | None) -> tuple[float, float, float, float] | None:
        if rect is None:
            return None
        off_x, off_y = self._offset
        return (
            off_x + rect.x * self._scale,
            off_y + rect.y * self._scale,
            rect.width * self._scale,
            rect.height * self._scale,
        )

    def _band_rect_widget(self) -> tuple[float, float, float, float] | None:
        return self._rect_widget(self._band_rect)

    def _subtitle_rect_widget(self) -> tuple[float, float, float, float] | None:
        return self._rect_widget(self._subtitle_rect)

    def _target_at(self, x: float, y: float) -> tuple[str, BandGeometry] | None:
        """Que se puede arrastrar bajo el punto (px del widget): el subtitulo (dibujado encima) o la banda."""
        for name, rect_widget, rect in (
            ("subtitle", self._subtitle_rect_widget(), self._subtitle_rect),
            ("band", self._band_rect_widget(), self._band_rect),
        ):
            if rect is not None and rect_widget is not None and self._point_in_rect(x, y, rect_widget):
                return name, rect
        return None

    @staticmethod
    def _point_in_rect(x: float, y: float, rect: tuple[float, float, float, float]) -> bool:
        rx, ry, rw, rh = rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    # ------------------------------------------------------------------
    # Arrastre de la banda
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        pos = event.position()
        target = self._target_at(pos.x(), pos.y())
        if target is None:
            return
        name, rect = target
        self._dragging = True
        self._drag_target = name
        canvas_x, canvas_y = self._widget_to_canvas(pos.x(), pos.y())
        self._drag_grab_offset = (canvas_x - rect.x, canvas_y - rect.y)
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        pos = event.position()
        if not self._dragging:
            self.setCursor(Qt.OpenHandCursor if self._target_at(pos.x(), pos.y()) else Qt.ArrowCursor)
            return
        canvas_x, canvas_y = self._widget_to_canvas(pos.x(), pos.y())
        new_left = canvas_x - self._drag_grab_offset[0]
        new_top = canvas_y - self._drag_grab_offset[1]
        if self._drag_target == "subtitle":
            self.subtitleRepositioned.emit(new_left, new_top)
        else:
            self.bandRepositioned.emit(new_left, new_top)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._dragging:
            self._dragging = False
            self._drag_target = None
            self.setCursor(Qt.OpenHandCursor)
