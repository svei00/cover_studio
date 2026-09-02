"""Pinta las primitivas de core.annotate con QPainter, para la edicion en
pantalla. El export usa SVG + resvg: la geometria es la misma (viene de las
primitivas), solo cambia el rasterizador, asi que el antialiasing del texto
puede diferir levemente."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF

from core.annotate import style
from core.annotate.primitives import PCircle, PEllipse, PImage, PLine, PPolygon, PRect, PText, Primitive

_FAMILIES = [name.strip() for name in style.FONT.split(",")]


def _color(hex_color: str, opacity: float = 1.0) -> QColor:
    color = QColor(hex_color)
    color.setAlphaF(opacity)
    return color


def _pen(
    hex_color: str | None,
    width: float,
    opacity: float = 1.0,
    round_join: bool = False,
    dash: tuple[float, float] | None = None,
) -> QPen:
    if not hex_color:
        return QPen(Qt.NoPen)
    pen = QPen(_color(hex_color, opacity), width)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.RoundJoin if round_join else Qt.MiterJoin)
    if dash and width > 0:
        pen.setDashPattern([dash[0] / width, dash[1] / width])  # Qt mide el trazo en multiplos del grosor
    return pen


def _brush(hex_color: str | None, opacity: float = 1.0) -> QBrush:
    return QBrush(_color(hex_color, opacity)) if hex_color else QBrush(Qt.NoBrush)


def _paint_text(painter: QPainter, p: PText) -> None:
    font = QFont()
    font.setFamilies(_FAMILIES)
    font.setPixelSize(max(1, round(p.size)))
    font.setBold(p.bold)
    metrics = QFontMetricsF(font)
    x = p.pos[0] - metrics.horizontalAdvance(p.text) / 2 if p.anchor == "middle" else p.pos[0]
    baseline = p.pos[1] + (metrics.ascent() - metrics.descent()) / 2
    path = QPainterPath()
    path.addText(x, baseline, font, p.text)
    if p.outline:
        outline = QPen(_color(p.outline), p.outline_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.strokePath(path, outline)
    painter.fillPath(path, _brush(p.color))


def _paint_image(painter: QPainter, p: PImage, images: Mapping[str, QImage]) -> None:
    image = images.get(p.key)
    if image is None or image.isNull():
        return
    path = QPainterPath()
    rect = QRectF(p.dest.x, p.dest.y, p.dest.w, p.dest.h)
    if p.shape in ("circle", "ellipse"):
        path.addEllipse(rect)
    else:
        path.addRoundedRect(rect, p.rx, p.rx)
    painter.save()
    painter.setClipPath(path)
    painter.drawImage(rect, image)
    painter.restore()


def paint_primitives(
    painter: QPainter,
    primitives: Sequence[Primitive],
    images: Mapping[str, QImage] | None = None,
) -> None:
    """Dibuja las primitivas en coordenadas de imagen (el llamador aplica la
    transformacion de vista al painter). `images` aporta el recorte de cada lupa."""
    for p in primitives:
        if isinstance(p, PImage):
            _paint_image(painter, p, images or {})
        elif isinstance(p, PRect):
            painter.setPen(_pen(p.stroke, p.width, p.opacity, dash=p.dash))
            painter.setBrush(_brush(p.fill, p.fill_opacity))
            rect = QRectF(p.rect.x, p.rect.y, p.rect.w, p.rect.h)
            if p.blend == "multiply":
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            if p.rx > 0:
                painter.drawRoundedRect(rect, p.rx, p.rx)
            else:
                painter.drawRect(rect)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        elif isinstance(p, PLine):
            painter.setPen(_pen(p.stroke, p.width, p.opacity))
            painter.drawLine(QPointF(*p.a), QPointF(*p.b))
        elif isinstance(p, PPolygon):
            painter.setPen(_pen(p.stroke, p.width, p.opacity, round_join=True))
            painter.setBrush(_brush(p.fill))
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in p.points]))
        elif isinstance(p, PCircle):
            painter.setPen(_pen(p.stroke, p.width, p.opacity, dash=p.dash))
            painter.setBrush(_brush(p.fill))
            painter.drawEllipse(QPointF(*p.center), p.r, p.r)
        elif isinstance(p, PEllipse):
            painter.setPen(_pen(p.stroke, p.width, p.opacity, dash=p.dash))
            painter.setBrush(_brush(p.fill))
            painter.drawEllipse(QPointF(*p.center), p.rx, p.ry)
        elif isinstance(p, PText):
            _paint_text(painter, p)
