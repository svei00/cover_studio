"""Dialogo del lienzo en blanco: tamano (preajustes, el de la imagen del portapapeles o personalizado) y color de fondo."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.annotate import blank
from ui.widgets import ColorPickerButton

_CUSTOM = "custom"


class BlankCanvasDialog(QDialog):
    """`size_px()` y `color()` dicen lo elegido. `clipboard_size` (ancho, alto de la imagen del portapapeles, si hay una) agrega
    el preajuste "Como la imagen del portapapeles": pegarla despues la deja a su tamano real, justo encajada."""

    def __init__(self, clipboard_size: tuple[int, int] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lienzo en blanco")
        self.setMinimumWidth(380)
        intro = QLabel(
            "Crea una captura base lisa para componer varias imagenes con Pegar encima (CTRL + MAYUS + V). "
            "Se guarda como cualquier captura."
        )
        intro.setWordWrap(True)

        self._preset = QComboBox()
        for label, size in blank.PRESETS:
            self._preset.addItem(label, size)
        self._preset.addItem("Personalizado", _CUSTOM)
        if clipboard_size is not None and self._valid(clipboard_size):
            # la imagen del portapapeles es lo mas probable que se quiera pegar: el dialogo arranca con ese tamano
            self._preset.insertItem(0, f"Como la imagen del portapapeles ({clipboard_size[0]} x {clipboard_size[1]})", clipboard_size)
            self._preset.setCurrentIndex(0)
        self._width = QSpinBox()
        self._height = QSpinBox()
        for spin in (self._width, self._height):
            spin.setRange(blank.MIN_SIDE, blank.MAX_SIDE)
            spin.setSuffix(" px")
        self._color = ColorPickerButton(blank.DEFAULT_COLOR)
        self._hint = QLabel()
        self._hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Tamano", self._preset)
        form.addRow("Ancho", self._width)
        form.addRow("Alto", self._height)
        form.addRow("Fondo", self._color)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crear")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        self._ok = buttons.button(QDialogButtonBox.Ok)
        self._preset.currentIndexChanged.connect(self._on_preset)
        self._width.valueChanged.connect(self._on_spin)
        self._height.valueChanged.connect(self._on_spin)
        self._on_preset()

    @staticmethod
    def _valid(size: tuple[int, int]) -> bool:
        try:
            blank.validate_size(size)
        except Exception:  # AnnotateError: fuera de rango (no se ofrece un tamano que se acotaria en silencio)
            return False
        return True

    def _on_preset(self) -> None:
        data = self._preset.currentData()
        if data != _CUSTOM:
            for spin, value in ((self._width, data[0]), (self._height, data[1])):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self._refresh_hint()

    def _on_spin(self) -> None:
        """Tocar el ancho o el alto a mano pasa el preajuste a Personalizado."""
        current = self._preset.currentData()
        if current == _CUSTOM or tuple(current) != (self._width.value(), self._height.value()):
            self._preset.blockSignals(True)
            self._preset.setCurrentIndex(self._preset.findData(_CUSTOM))
            self._preset.blockSignals(False)
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        w, h = self._width.value(), self._height.value()
        try:
            blank.validate_size((w, h))
        except Exception as exc:  # AnnotateError: demasiados megapixeles
            self._hint.setText(str(exc))
            self._ok.setEnabled(False)
        else:
            self._hint.setText(f"{w} x {h} px ({w * h / 1e6:.1f} MP)")
            self._ok.setEnabled(True)

    def size_px(self) -> tuple[int, int]:
        return self._width.value(), self._height.value()

    def color(self) -> str:
        return self._color.hex_color().upper()
