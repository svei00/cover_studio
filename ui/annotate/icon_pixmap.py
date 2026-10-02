"""Miniaturas de los iconos para botones, menus y combos: se pintan con las MISMAS primitivas que la captura
(core.annotate.primitives.icon_primitives), asi lo que se ve en el boton es lo que se coloca."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from core.annotate.model import Icon, IconKind, IconStyle
from core.annotate.primitives import icon_primitives
from ui.annotate.painter import paint_primitives

ICON_LABELS: dict[IconKind, str] = {
    IconKind.CHECK: "Check",
    IconKind.CROSS: "Cruz",
    IconKind.WARNING: "Alerta",
    IconKind.INFO: "Info",
    IconKind.QUESTION: "Pregunta",
    IconKind.STAR: "Estrella",
    IconKind.PLUS: "Mas",
    IconKind.MINUS: "Menos",
}


def icon_pixmap(kind: IconKind, style: IconStyle = IconStyle.SEAL, px: int = 24, ratio: float = 2.0) -> QPixmap:
    """Miniatura cuadrada de `px` px logicos (se pinta a `ratio` veces para que se vea nitida en pantallas de alta densidad)."""
    side = round(px * ratio)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    radius = px / 2 * 0.86   # deja sitio al borde blanco
    center = px / 2
    painter.translate(0.0, 0.0)
    paint_primitives(painter, icon_primitives(Icon("preview", (center, center), kind, style, size=radius, ring=False), 1.0))
    painter.end()
    return pixmap


def icon_for(kind: IconKind, style: IconStyle = IconStyle.SEAL, px: int = 24) -> QIcon:
    return QIcon(icon_pixmap(kind, style, px))
