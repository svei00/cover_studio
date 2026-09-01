"""Panel de propiedades de la anotacion seleccionada. Cada control empuja un
cambio al EditController (que lo fusiona en un solo paso de deshacer)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.annotate.bounds import required_padding
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
from core.annotate.palette import BRAND_PALETTE, PALETTE_LABELS
from core.annotate.primitives import doc_scale
from core.annotate.style import MAX_SCALE, MIN_SCALE, TEXT_PRESETS
from ui.annotate.controller import EditController
from ui.widgets import ColorPickerButton

ARROW_LABELS = {
    ArrowSide.AUTO: "Automatica",
    ArrowSide.LEFT: "Izquierda",
    ArrowSide.RIGHT: "Derecha",
    ArrowSide.TOP: "Arriba",
    ArrowSide.BOTTOM: "Abajo",
    ArrowSide.NONE: "Sin flecha",
}
ALIGN_LABELS = {TextAlign.LEFT: "Izquierda", TextAlign.CENTER: "Centrada"}
LENS_SHAPE_LABELS = {
    LensShape.CIRCLE: "Circular",
    LensShape.ELLIPSE: "Ovalada",
    LensShape.ROUNDED: "Rectangular",
}
PRESET_LABELS = {"nota": "Nota", "exito": "Exito", "alerta": "Alerta", "libre": "Libre (con contorno)"}

_PAGE_EMPTY, _PAGE_MARKER, _PAGE_ARROW, _PAGE_STEP, _PAGE_TEXT, _PAGE_REDACTION, _PAGE_LENS = range(7)


class _ColorRow(QWidget):
    """Selector de color de una anotacion, con un boton para volver al color de la
    paleta del documento (cuando la anotacion tiene uno propio)."""

    changed = Signal(object)  # "#RRGGBB" o None (volver al de la paleta)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._silent = False
        self._picker = ColorPickerButton("#000000")
        self._picker.colorChanged.connect(self._on_picked)
        self._reset = QToolButton()
        self._reset.setText("Paleta")
        self._reset.setToolTip("Volver al color de la paleta del documento")
        self._reset.clicked.connect(lambda: self.changed.emit(None))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._picker, stretch=1)
        layout.addWidget(self._reset)

    def set_value(self, effective: str, overridden: bool) -> None:
        """Muestra el color vigente sin emitir `changed` (no es una edicion del usuario)."""
        self._silent = True
        try:
            self._picker.set_hex_color(effective)
        finally:
            self._silent = False
        self._reset.setEnabled(overridden)

    def hex_color(self) -> str:
        return self._picker.hex_color()

    def _on_picked(self, hex_color: str) -> None:
        if not self._silent:
            self.changed.emit(hex_color)


class PropertiesPanel(QWidget):
    def __init__(self, controller: EditController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = controller
        self._syncing = False
        self.setFixedWidth(290)

        self._title = QLabel("Propiedades")
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_document_page())
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
        self.sync()  # estado inicial coherente: sin captura no se muestran los grupos del documento

    # ------------------------------------------------------------------
    # Paginas
    # ------------------------------------------------------------------

    def _build_document_page(self) -> QWidget:
        """Pagina sin seleccion: ayuda breve y propiedades del documento."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Selecciona una anotacion para editarla, o elige una herramienta y dibuja sobre la captura.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._doc_group = QGroupBox("Documento")
        form = QFormLayout(self._doc_group)
        self._padding_spin = QSpinBox()
        self._padding_spin.setRange(0, 400)
        self._padding_spin.setSuffix(" px")
        self._padding_spin.setToolTip("Margen extra alrededor de la captura, para que el resplandor no se recorte")
        self._padding_spin.valueChanged.connect(self._on_padding_changed)
        self._scale_auto = QCheckBox("Escala automatica")
        self._scale_auto.setToolTip("Los trazos se escalan segun el ancho de la captura")
        self._scale_auto.toggled.connect(self._on_scale_auto_toggled)
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(MIN_SCALE, MAX_SCALE)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setDecimals(2)
        self._scale_spin.valueChanged.connect(self._on_scale_changed)
        self._clip_notice = QLabel()
        self._clip_notice.setWordWrap(True)
        self._clip_notice.setStyleSheet("color: #E8B95C;")
        self._clip_btn = QPushButton()
        self._clip_btn.clicked.connect(self._on_add_padding_clicked)
        form.addRow("Margen extra", self._padding_spin)
        form.addRow(self._scale_auto)
        form.addRow("Escala de trazo", self._scale_spin)
        form.addRow(self._clip_notice)
        form.addRow(self._clip_btn)
        layout.addWidget(self._doc_group)

        self._colors_group = QGroupBox("Colores")
        colors_form = QFormLayout(self._colors_group)
        self._palette_pickers: dict[str, ColorPickerButton] = {}
        for key, label in PALETTE_LABELS.items():
            picker = ColorPickerButton(getattr(BRAND_PALETTE, key))
            picker.colorChanged.connect(lambda hex_color, k=key: self._on_palette_color(k, hex_color))
            self._palette_pickers[key] = picker
            colors_form.addRow(label, picker)
        self._restore_btn = QPushButton("Restaurar colores de marca")
        self._restore_btn.setToolTip("Vuelve a los colores de las infografias de Excel Solutions")
        self._restore_btn.clicked.connect(self._on_restore_palette)
        colors_form.addRow(self._restore_btn)
        layout.addWidget(self._colors_group)
        layout.addStretch(1)
        return page

    def _on_palette_color(self, key: str, hex_color: str) -> None:
        if not self._syncing and self._c.doc is not None:
            self._c.set_palette(replace(self._c.doc.palette, **{key: hex_color}))

    def _on_restore_palette(self) -> None:
        self._c.set_palette(BRAND_PALETTE)

    def _color_row(self, form: QFormLayout, label: str, field: str) -> _ColorRow:
        """Fila de color de una anotacion: el campo `field` (None = el de la paleta)."""
        row = _ColorRow()
        row.changed.connect(lambda value, f=field: self._apply_color(f, value))
        form.addRow(label, row)
        return row

    def _on_padding_changed(self, value: int) -> None:
        if not self._syncing:
            self._c.set_padding(value)

    def _on_scale_auto_toggled(self, auto: bool) -> None:
        if self._syncing or self._c.doc is None:
            return
        self._c.set_style_scale(None if auto else round(doc_scale(self._c.doc), 2))

    def _on_scale_changed(self, value: float) -> None:
        if not self._syncing and not self._scale_auto.isChecked():
            self._c.set_style_scale(round(value, 2))

    def _on_add_padding_clicked(self) -> None:
        if self._c.doc is not None:
            self._c.set_padding(required_padding(self._c.doc))

    def _build_marker_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._marker_arrow = QComboBox()
        for side, label in ARROW_LABELS.items():
            self._marker_arrow.addItem(label, side.value)
        self._marker_arrow.currentIndexChanged.connect(
            lambda _i: self._apply(arrow=ArrowSide(self._marker_arrow.currentData()))
        )
        self._marker_glow = QCheckBox("Resplandor")
        self._marker_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow("Lado de la flecha", self._marker_arrow)
        form.addRow(self._marker_glow)
        self._marker_stroke = self._color_row(form, "Recuadro", "stroke_color")
        self._marker_arrow_color = self._color_row(form, "Flecha", "arrow_color")
        self._marker_glow_color = self._color_row(form, "Resplandor", "glow_color")
        return page

    def _build_arrow_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._arrow_glow = QCheckBox("Resplandor")
        self._arrow_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow(self._arrow_glow)
        self._arrow_color = self._color_row(form, "Flecha", "color")
        self._arrow_glow_color = self._color_row(form, "Resplandor", "glow_color")
        return page

    def _build_step_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._step_number = QSpinBox()
        self._step_number.setRange(1, 999)
        self._step_number.valueChanged.connect(lambda v: self._apply(number=v))
        form.addRow("Numero", self._step_number)
        self._step_color = self._color_row(form, "Color", "color")
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
        self._lens_corner = QSpinBox()
        self._lens_corner.setRange(0, 50)
        self._lens_corner.setSuffix(" %")
        self._lens_corner.setToolTip("0 = esquinas rectas; 50 = tan redondeadas que parece una capsula")
        self._lens_corner.valueChanged.connect(lambda v: self._apply(corner=v / 100))
        form.addRow("Esquinas", self._lens_corner)
        self._lens_form = form
        form.addRow(self._lens_connector)
        self._lens_frame = self._color_row(form, "Marco", "frame_color")
        form.addRow(replace_btn)
        return page

    # ------------------------------------------------------------------
    # Edicion y sincronizacion
    # ------------------------------------------------------------------

    def _apply(self, **changes) -> None:
        if not self._syncing:
            self._c.edit_selected(**changes)

    def _apply_color(self, field: str, value: str | None) -> None:
        """Un color elegido en el dialogo es una decision completa: su propio paso de deshacer."""
        if not self._syncing:
            self._c.edit_selected(_merge=False, **{field: value})

    def _on_preset_chosen(self, index: int) -> None:
        key = self._text_preset.itemData(index)
        if key:
            if not self._syncing:  # elegir un preset es una decision completa: su propio paso
                self._c.edit_selected(_merge=False, **{"border_width": 2.5, **TEXT_PRESETS[key]})
        self._text_preset.setCurrentIndex(0)

    def focus_text(self) -> None:
        self._text_edit.setFocus()
        self._text_edit.selectAll()

    def sync(self) -> None:
        """Muestra la pagina de la anotacion seleccionada con sus valores. No
        reescribe un control que ya tiene el valor (asi no se pierde el cursor
        mientras se escribe)."""
        item = self._c.selected_item()
        pal = self._c.doc.palette if self._c.doc is not None else BRAND_PALETTE
        self._syncing = True
        try:
            if isinstance(item, Marker):
                self._pages.setCurrentIndex(_PAGE_MARKER)
                self._title.setText("Marcador")
                self._set_combo(self._marker_arrow, item.arrow.value)
                self._marker_glow.setChecked(item.glow)
                self._marker_stroke.set_value(item.stroke_color or pal.marker, item.stroke_color is not None)
                self._marker_arrow_color.set_value(item.arrow_color or pal.arrow, item.arrow_color is not None)
                self._marker_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
            elif isinstance(item, Arrow):
                self._pages.setCurrentIndex(_PAGE_ARROW)
                self._title.setText("Flecha")
                self._arrow_glow.setChecked(item.glow)
                self._arrow_color.set_value(item.color or pal.arrow, item.color is not None)
                self._arrow_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
            elif isinstance(item, StepBadge):
                self._pages.setCurrentIndex(_PAGE_STEP)
                self._title.setText("Paso numerado")
                if self._step_number.value() != item.number:
                    self._step_number.setValue(item.number)
                self._step_color.set_value(item.color or pal.step, item.color is not None)
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
                if self._lens_corner.value() != round(item.corner * 100):
                    self._lens_corner.setValue(round(item.corner * 100))
                self._lens_form.setRowVisible(self._lens_corner, item.shape is LensShape.ROUNDED)
                self._lens_connector.setChecked(item.connector)
                self._lens_frame.set_value(item.frame_color or pal.lens, item.frame_color is not None)
            elif isinstance(item, Redaction):
                self._pages.setCurrentIndex(_PAGE_REDACTION)
                self._title.setText("Pixelado")
                if self._redaction_block.value() != item.block:
                    self._redaction_block.setValue(item.block)
            else:
                self._pages.setCurrentIndex(_PAGE_EMPTY)
                self._title.setText("Propiedades")
            self._sync_document()
        finally:
            self._syncing = False

    def _sync_document(self) -> None:
        doc = self._c.doc
        self._doc_group.setVisible(doc is not None)
        self._colors_group.setVisible(doc is not None)
        if doc is None:
            return
        for key, picker in self._palette_pickers.items():
            picker.set_hex_color(getattr(doc.palette, key))
        self._restore_btn.setEnabled(doc.palette != BRAND_PALETTE)
        if self._padding_spin.value() != doc.padding:
            self._padding_spin.setValue(doc.padding)
        auto = doc.style_scale is None
        self._scale_auto.setChecked(auto)
        self._scale_spin.setEnabled(not auto)
        shown = round(doc_scale(doc), 2)
        if abs(self._scale_spin.value() - shown) > 1e-9:
            self._scale_spin.setValue(shown)
        # el aviso del recorte solo se calcula con la pagina visible (no durante los arrastres)
        needed = required_padding(doc) if self._pages.currentIndex() == _PAGE_EMPTY else 0
        clipped = needed > doc.padding
        self._clip_notice.setVisible(clipped)
        self._clip_btn.setVisible(clipped)
        if clipped:
            self._clip_notice.setText("El resplandor o alguna etiqueta se recorta en el borde de la captura.")
            self._clip_btn.setText(f"Agregar margen de {needed} px")

    @staticmethod
    def _set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
