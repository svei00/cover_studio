"""Dialogo para editar los colores de marca (los valores por defecto de Portada y de Anotar)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.brand import ANNOTATE_COLORS, COVER_COLORS, DEFAULT_BRAND, MAX_NAME_LENGTH, Brand, normalize
from ui.widgets import ColorPickerButton


class BrandDialog(QDialog):
    """Nombre y colores de la marca. `brand()` es lo que quedo en el dialogo; `apply_now()` dice si ademas hay que
    aplicarlo YA al diseno de Portada y al documento abierto de Anotar (si no, solo cambian los valores por defecto:
    lo nuevo y el boton "Restaurar colores de marca")."""

    def __init__(self, brand: Brand, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colores de marca")
        self.setMinimumWidth(420)

        intro = QLabel(
            "Son los colores por defecto de Portada y de Anotar. Se guardan en tu carpeta de usuario "
            "(brand.json); las capturas ya guardadas conservan sus colores."
        )
        intro.setWordWrap(True)

        self._name = QLineEdit(brand.name)
        self._name.setMaxLength(MAX_NAME_LENGTH)
        self._name.setPlaceholderText(DEFAULT_BRAND.name)
        name_form = QFormLayout()
        name_form.addRow("Marca", self._name)

        self._pickers: dict[str, ColorPickerButton] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(name_form)
        layout.addWidget(self._group("Portada", COVER_COLORS, brand))
        layout.addWidget(self._group("Anotar", ANNOTATE_COLORS, brand))

        self._reset_btn = QPushButton(f"Restablecer a {DEFAULT_BRAND.name}")
        self._reset_btn.clicked.connect(self._reset)
        layout.addWidget(self._reset_btn)

        self._apply_now = QCheckBox("Aplicar ahora al diseno de Portada y a la captura abierta")
        self._apply_now.setToolTip(
            "Sin marcar, solo cambian los valores por defecto (lo nuevo y 'Restaurar colores de marca'); "
            "tu diseno y tus anotaciones actuales no se tocan."
        )
        layout.addWidget(self._apply_now)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _group(self, title: str, colors: tuple[tuple[str, str], ...], brand: Brand) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        for key, label in colors:
            picker = ColorPickerButton(getattr(brand, key))
            self._pickers[key] = picker
            form.addRow(label, picker)
        return box

    def _reset(self) -> None:
        self._name.setText(DEFAULT_BRAND.name)
        for key, picker in self._pickers.items():
            picker.set_hex_color(getattr(DEFAULT_BRAND, key))

    def brand(self) -> Brand:
        values = {key: picker.hex_color() for key, picker in self._pickers.items()}
        return normalize(Brand(name=self._name.text(), **values))

    def apply_now(self) -> bool:
        return self._apply_now.isChecked()
