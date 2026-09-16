"""Layout que acomoda sus widgets en filas y baja a la siguiente cuando no caben (como el texto). Sirve
para barras de herramientas largas: en vez de obligar a la ventana a medir tanto de ancho como la fila
entera, la fila se parte en dos. Basado en el ejemplo "Flow Layout" de Qt."""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, h_spacing: int = 6, v_spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    # --- QLayout ------------------------------------------------------------

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 (Qt override)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt override)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    # --- reparto -----------------------------------------------------------------

    def _layout(self, rect: QRect, apply: bool) -> int:
        """Reparte los items por filas dentro de `rect`; devuelve el alto usado."""
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        for item in self._items:
            if item.widget() is not None and not item.widget().isVisibleTo(item.widget().parentWidget()):
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h
            if next_x - self._h > area.right() + 1 and row_h > 0:   # no cabe: nueva fila
                x = area.x()
                y += row_h + self._v
                next_x = x + hint.width() + self._h
                row_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


def spacer(width: int) -> QWidget:
    """Hueco fijo para separar grupos dentro de un FlowLayout."""
    widget = QWidget()
    widget.setFixedSize(width, 1)
    widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return widget
