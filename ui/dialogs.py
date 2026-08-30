"""Dialogos compartidos entre pestanas."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class OverwriteConfirmDialog(QDialog):
    """Exige escribir SOBRESCRIBIR para habilitar el boton de confirmar,
    con friccion real antes de perder la imagen original."""

    CONFIRM_WORD = "SOBRESCRIBIR"

    def __init__(self, parent: QWidget | None = None, subject: str = "la foto limpia sin banner") -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirmar sobrescritura")

        icon_label = QLabel()
        style = self.style()
        if style is not None:
            icon_label.setPixmap(style.standardIcon(QStyle.SP_MessageBoxWarning).pixmap(32, 32))

        message = QLabel(
            "Vas a sobrescribir la imagen original. Esta accion no se puede "
            f"deshacer y perderas {subject}."
        )
        message.setWordWrap(True)

        header = QHBoxLayout()
        header.addWidget(icon_label)
        header.addWidget(message, stretch=1)

        self._input = QLineEdit()
        self._input.setPlaceholderText(f"Escribe {self.CONFIRM_WORD} para continuar")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self._ok_button.setText("Sobrescribir")
        self._ok_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._input.textChanged.connect(
            lambda text: self._ok_button.setEnabled(text == self.CONFIRM_WORD)
        )

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._input)
        layout.addWidget(buttons)
