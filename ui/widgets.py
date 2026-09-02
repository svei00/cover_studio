"""Widgets reutilizables de la GUI: selector de color con swatch y slider
sincronizado con spinbox."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)


class ColorPickerButton(QWidget):
    """Swatch clicable + texto hex. Abre QColorDialog al hacer click y
    emite colorChanged con el nuevo color en formato #RRGGBB."""

    colorChanged = Signal(str)

    def __init__(self, initial_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hex = initial_hex

        self._swatch = QLabel()
        self._swatch.setFixedSize(28, 20)
        self._swatch.setCursor(Qt.PointingHandCursor)
        self._swatch.setFrameShape(QLabel.Box)

        self._hex_label = QLabel(initial_hex.upper())
        self._hex_label.setMinimumWidth(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._swatch)
        layout.addWidget(self._hex_label)
        layout.addStretch(1)

        self._swatch.mousePressEvent = self._on_swatch_clicked  # type: ignore[assignment]
        self._update_swatch()

    def hex_color(self) -> str:
        return self._hex

    def set_hex_color(self, hex_color: str) -> None:
        if hex_color == self._hex:
            return
        self._hex = hex_color
        self._update_swatch()
        self.colorChanged.emit(self._hex)

    def _update_swatch(self) -> None:
        self._swatch.setStyleSheet(f"background-color: {self._hex}; border: 1px solid #00000040;")
        self._hex_label.setText(self._hex.upper())

    def _on_swatch_clicked(self, _event) -> None:
        color = QColorDialog.getColor(QColor(self._hex), self, "Elegir color")
        if color.isValid():
            self.set_hex_color(color.name())


class ColorSwatchRow(QWidget):
    """Fila de muestras de color para elegir de un clic entre unos pocos colores fijos
    (p. ej. los de un resaltador). Emite colorPicked con el #RRGGBB elegido; set_current marca la
    muestra que coincide con el color vigente (si no coincide ninguna, no marca ninguna)."""

    colorPicked = Signal(str)

    def __init__(self, swatches: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for name, hex_color in swatches:
            button = QPushButton()
            button.setFixedSize(30, 22)
            button.setToolTip(name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, c=hex_color: self.colorPicked.emit(c))
            self._buttons[hex_color.upper()] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.set_current(None)

    def set_current(self, hex_color: str | None) -> None:
        current = hex_color.upper() if hex_color else None
        for color, button in self._buttons.items():
            border = "2px solid #FFFFFF" if color == current else "1px solid #00000060"
            button.setStyleSheet(f"background-color: {color}; border: {border}; border-radius: 3px;")


class SliderSpinBox(QWidget):
    """Slider + spinbox sincronizados. Trabaja en enteros; para valores con
    decimales usa `scale` (p. ej. scale=100 para pasos de 0.01)."""

    valueChanged = Signal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        initial: float,
        step: float = 1.0,
        suffix: str = "",
        scale: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = scale

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setMinimum(round(minimum * scale))
        self._slider.setMaximum(round(maximum * scale))
        self._slider.setSingleStep(max(1, round(step * scale)))

        if scale == 1:
            self._spin: QSpinBox | QDoubleSpinBox = QSpinBox()
            self._spin.setMinimum(int(minimum))
            self._spin.setMaximum(int(maximum))
            self._spin.setSingleStep(int(step))
        else:
            self._spin = QDoubleSpinBox()
            self._spin.setDecimals(len(str(scale)) - 1)
            self._spin.setMinimum(minimum)
            self._spin.setMaximum(maximum)
            self._spin.setSingleStep(step)
        if suffix:
            self._spin.setSuffix(suffix)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._slider, stretch=1)
        layout.addWidget(self._spin)

        self.set_value(initial)
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._spin.valueChanged.connect(self._on_spin_changed)

    def value(self) -> float:
        return self._spin.value()

    def set_value(self, value: float) -> None:
        self._slider.blockSignals(True)
        self._spin.blockSignals(True)
        self._slider.setValue(round(value * self._scale))
        self._spin.setValue(value)
        self._slider.blockSignals(False)
        self._spin.blockSignals(False)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (Qt override)
        super().setEnabled(enabled)
        self._slider.setEnabled(enabled)
        self._spin.setEnabled(enabled)

    def _on_slider_changed(self, raw: int) -> None:
        value = raw / self._scale
        self._spin.blockSignals(True)
        self._spin.setValue(value)
        self._spin.blockSignals(False)
        self.valueChanged.emit(value)

    def _on_spin_changed(self, value: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(round(value * self._scale))
        self._slider.blockSignals(False)
        self.valueChanged.emit(value)
