"""Iconos de los botones de alinear y distribuir, dibujados en codigo (nada de archivos): una o dos lineas de referencia y
las barras que se acomodan contra ellas, como en Photoshop y Figma. Siguen el color del texto del tema."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from core.annotate.align import Align, Distribute

SIZE = 20   # px logicos
Rect4 = tuple[float, float, float, float]   # x, y, ancho, alto en un cuadro de 20 x 20
Parts = tuple[tuple[Rect4, ...], tuple[Rect4, ...]]   # (lineas de referencia, barras)

_ALIGN: dict[Align, Parts] = {
    Align.LEFT: (((2.0, 2.0, 1.5, 16.0),), ((3.5, 5.0, 12.0, 4.0), (3.5, 11.0, 7.0, 4.0))),
    Align.CENTER_H: (((9.25, 2.0, 1.5, 16.0),), ((4.0, 5.0, 12.0, 4.0), (6.5, 11.0, 7.0, 4.0))),
    Align.RIGHT: (((16.5, 2.0, 1.5, 16.0),), ((4.5, 5.0, 12.0, 4.0), (9.5, 11.0, 7.0, 4.0))),
    Align.TOP: (((2.0, 2.0, 16.0, 1.5),), ((5.0, 3.5, 4.0, 12.0), (11.0, 3.5, 4.0, 7.0))),
    Align.MIDDLE_V: (((2.0, 9.25, 16.0, 1.5),), ((5.0, 4.0, 4.0, 12.0), (11.0, 6.5, 4.0, 7.0))),
    Align.BOTTOM: (((2.0, 16.5, 16.0, 1.5),), ((5.0, 4.5, 4.0, 12.0), (11.0, 9.5, 4.0, 7.0))),
}
_DISTRIBUTE: dict[Distribute, Parts] = {
    Distribute.HORIZONTAL: (((2.0, 2.0, 1.5, 16.0), (16.5, 2.0, 1.5, 16.0)), ((8.0, 5.0, 4.0, 10.0),)),
    Distribute.VERTICAL: (((2.0, 2.0, 16.0, 1.5), (2.0, 16.5, 16.0, 1.5)), ((5.0, 8.0, 10.0, 4.0),)),
}


def _paint(parts: Parts, enabled: bool, ratio: float = 2.0) -> QPixmap:
    side = round(SIZE * ratio)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(ratio)
    group = QPalette.Active if enabled else QPalette.Disabled
    color = QApplication.palette().color(group, QPalette.ButtonText)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    lines, bars = parts
    painter.setBrush(QColor(color))
    for rect in lines:
        painter.drawRect(QRectF(*rect))
    fill = QColor(color)
    fill.setAlpha(210 if enabled else 120)
    painter.setBrush(fill)
    for rect in bars:
        painter.drawRoundedRect(QRectF(*rect), 1.0, 1.0)
    painter.end()
    return pixmap


def _icon(parts: Parts) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_paint(parts, True), QIcon.Normal)
    icon.addPixmap(_paint(parts, False), QIcon.Disabled)
    return icon


def align_icon(mode: Align) -> QIcon:
    return _icon(_ALIGN[mode])


def distribute_icon(axis: Distribute) -> QIcon:
    return _icon(_DISTRIBUTE[axis])
