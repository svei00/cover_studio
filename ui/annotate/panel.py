"""Panel de propiedades de la anotacion seleccionada. Cada control empuja un
cambio al EditController (que lo fusiona en un solo paso de deshacer)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.annotate.lens import MAX_ZOOM, MIN_ZOOM, RECOMMENDED_MAX_ZOOM
from core.annotate.model import (
    Arrow,
    ArrowSide,
    LensShape,
    Magnifier,
    Marker,
    Redaction,
    StepBadge,
    TextAlign,
    TextLabel,
)
from core.annotate.style import TEXT_PRESETS
from ui.annotate.controller import EditController

ARROW_LABELS = {
    ArrowSide.AUTO: "Automatica",
    ArrowSide.LEFT: "Izquierda",
    ArrowSide.RIGHT: "Derecha",
    ArrowSide.TOP: "Arriba",
    ArrowSide.BOTTOM: "Abajo",
    ArrowSide.NONE: "Sin flecha",
}
ALIGN_LABELS = {TextAlign.LEFT: "Izquierda", TextAlign.CENTER: "Centrada"}
LENS_SHAPE_LABELS = {LensShape.CIRCLE: "Circular", LensShape.ROUNDED: "Rectangular redondeada"}
PRESET_LABELS = {"nota": "Nota", "exito": "Exito", "alerta": "Alerta", "libre": "Libre (con contorno)"}

_PAGE_EMPTY, _PAGE_MARKER, _PAGE_ARROW, _PAGE_STEP, _PAGE_TEXT, _PAGE_REDACTION, _PAGE_LENS = range(7)


class PropertiesPanel(QWidget):
    def __init__(self, controller: EditController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = controller
        self._syncing = False
        self.setFixedWidth(250)

        self._title = QLabel("Propiedades")
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)

        self._pages = QStackedWidget()
        hint = QLabel("Selecciona una anotacion para editarla, o elige una herramienta y dibuja sobre la captura.")
        hint.setWordWrap(True)
        self._pages.addWidget(hint)
        self._pages.addWidget(self._build_marker_page())
        self._pages.addWidget(self._build_arrow_page())
        self._pages.addWidget(self._build_step_page())
        self._pages.addWidget(self._build_text_page())
        self._pages.addWidget(self._build_redaction_page())
        self._pages.addWidget(self._build_lens_page())

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._pages)
        layout.addStretch(1)

        controller.selectionChanged.connect(self.sync)
        controller.changed.connect(self.sync)
        controller.textEditRequested.connect(self.focus_text)

    # ------------------------------------------------------------------
    # Paginas
    # ------------------------------------------------------------------

    def _build_marker_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._marker_arrow = QComboBox()
        for side, label in ARROW_LABELS.items():
            self._marker_arrow.addItem(label, side.value)
        self._marker_arrow.currentIndexChanged.connect(
            lambda _i: self._apply(arrow=ArrowSide(self._marker_arrow.currentData()))
        )
        self._marker_glow = QCheckBox("Resplandor dorado")
        self._marker_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow("Flecha", self._marker_arrow)
        form.addRow(self._marker_glow)
        return page

    def _build_arrow_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._arrow_glow = QCheckBox("Resplandor dorado")
        self._arrow_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow(self._arrow_glow)
        return page

    def _build_step_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._step_number = QSpinBox()
        self._step_number.setRange(1, 999)
        self._step_number.valueChanged.connect(lambda v: self._apply(number=v))
        form.addRow("Numero", self._step_number)
        return page

    def _build_text_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._text_edit = QPlainTextEdit()
        self._text_edit.setFixedHeight(84)
        self._text_edit.textChanged.connect(lambda: self._apply(text=self._text_edit.toPlainText()))

        self._text_preset = QComboBox()
        self._text_preset.addItem("Elegir preset...", None)
        for key, label in PRESET_LABELS.items():
            self._text_preset.addItem(label, key)
        self._text_preset.activated.connect(self._on_preset_chosen)

        self._text_size = QSpinBox()
        self._text_size.setRange(8, 300)
        self._text_size.valueChanged.connect(lambda v: self._apply(size=float(v)))
        self._text_bold = QCheckBox("Negrita")
        self._text_bold.toggled.connect(lambda on: self._apply(bold=on))
        self._text_align = QComboBox()
        for align, label in ALIGN_LABELS.items():
            self._text_align.addItem(label, align.value)
        self._text_align.currentIndexChanged.connect(
            lambda _i: self._apply(align=TextAlign(self._text_align.currentData()))
        )

        form.addRow(self._text_edit)
        form.addRow("Estilo", self._text_preset)
        form.addRow("Tamano", self._text_size)
        form.addRow(self._text_bold)
        form.addRow("Alineacion", self._text_align)
        return page

    def _build_redaction_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._redaction_block = QSpinBox()
        self._redaction_block.setRange(2, 200)
        self._redaction_block.valueChanged.connect(lambda v: self._apply(block=v))
        form.addRow("Tamano del bloque", self._redaction_block)
        note = QLabel("El pixelado es irreversible en la imagen exportada.")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _build_lens_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._lens_zoom = QDoubleSpinBox()
        self._lens_zoom.setRange(MIN_ZOOM, MAX_ZOOM)
        self._lens_zoom.setSingleStep(0.25)
        self._lens_zoom.setDecimals(2)
        self._lens_zoom.setSuffix(" x")
        self._lens_zoom.valueChanged.connect(lambda v: self._apply(zoom=float(v)))
        self._lens_warning = QLabel(
            "Con zoom alto el texto de una captura se ve borroso. Para texto legible, "
            "captura con mas zoom en Excel."
        )
        self._lens_warning.setWordWrap(True)
        self._lens_warning.setStyleSheet("color: #E8B95C;")
        self._lens_warning.setVisible(False)
        self._lens_shape = QComboBox()
        for shape, label in LENS_SHAPE_LABELS.items():
            self._lens_shape.addItem(label, shape.value)
        self._lens_shape.currentIndexChanged.connect(
            lambda _i: self._apply(shape=LensShape(self._lens_shape.currentData()))
        )
        self._lens_connector = QCheckBox("Conector entre origen y lente")
        self._lens_connector.toggled.connect(lambda on: self._apply(connector=on))
        replace_btn = QPushButton("Recolocar lupa")
        replace_btn.setToolTip("Coloca el lente en el lado con mas espacio, sin cubrir su origen")
        replace_btn.clicked.connect(self._c.auto_place_selected_lens)
        form.addRow("Zoom", self._lens_zoom)
        form.addRow(self._lens_warning)
        form.addRow("Forma", self._lens_shape)
        form.addRow(self._lens_connector)
        form.addRow(replace_btn)
        return page

    # ------------------------------------------------------------------
    # Edicion y sincronizacion
    # ------------------------------------------------------------------

    def _apply(self, **changes) -> None:
        if not self._syncing:
            self._c.edit_selected(**changes)

    def _on_preset_chosen(self, index: int) -> None:
        key = self._text_preset.itemData(index)
        if key:
            self._apply(**{"border_width": 2.5, **TEXT_PRESETS[key]})
        self._text_preset.setCurrentIndex(0)

    def focus_text(self) -> None:
        self._text_edit.setFocus()
        self._text_edit.selectAll()

    def sync(self) -> None:
        """Muestra la pagina de la anotacion seleccionada con sus valores. No
        reescribe un control que ya tiene el valor (asi no se pierde el cursor
        mientras se escribe)."""
        item = self._c.selected_item()
        self._syncing = True
        try:
            if isinstance(item, Marker):
                self._pages.setCurrentIndex(_PAGE_MARKER)
                self._title.setText("Marcador")
                self._set_combo(self._marker_arrow, item.arrow.value)
                self._marker_glow.setChecked(item.glow)
            elif isinstance(item, Arrow):
                self._pages.setCurrentIndex(_PAGE_ARROW)
                self._title.setText("Flecha")
                self._arrow_glow.setChecked(item.glow)
            elif isinstance(item, StepBadge):
                self._pages.setCurrentIndex(_PAGE_STEP)
                self._title.setText("Paso numerado")
                if self._step_number.value() != item.number:
                    self._step_number.setValue(item.number)
            elif isinstance(item, TextLabel):
                self._pages.setCurrentIndex(_PAGE_TEXT)
                self._title.setText("Etiqueta de texto")
                if self._text_edit.toPlainText() != item.text:
                    self._text_edit.setPlainText(item.text)
                if self._text_size.value() != round(item.size):
                    self._text_size.setValue(round(item.size))
                self._text_bold.setChecked(item.bold)
                self._set_combo(self._text_align, item.align.value)
            elif isinstance(item, Magnifier):
                self._pages.setCurrentIndex(_PAGE_LENS)
                self._title.setText("Lupa")
                if abs(self._lens_zoom.value() - item.zoom) > 1e-9:
                    self._lens_zoom.setValue(item.zoom)
                self._lens_warning.setVisible(item.zoom > RECOMMENDED_MAX_ZOOM)
                self._set_combo(self._lens_shape, item.shape.value)
                self._lens_connector.setChecked(item.connector)
            elif isinstance(item, Redaction):
                self._pages.setCurrentIndex(_PAGE_REDACTION)
                self._title.setText("Pixelado")
                if self._redaction_block.value() != item.block:
                    self._redaction_block.setValue(item.block)
            else:
                self._pages.setCurrentIndex(_PAGE_EMPTY)
                self._title.setText("Propiedades")
        finally:
            self._syncing = False

    @staticmethod
    def _set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
