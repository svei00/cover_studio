"""Panel de propiedades de la anotacion seleccionada. Cada control empuja un
cambio al EditController (que lo fusiona en un solo paso de deshacer)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.annotate.bounds import items_outside_view, required_padding
from core.annotate.lens import MAX_ZOOM, MIN_ZOOM, RECOMMENDED_MAX_ZOOM
from core.annotate.model import (
    Arrow,
    ArrowSide,
    HeadStyle,
    Highlight,
    HighlightMode,
    LensShape,
    LineStyle,
    Magnifier,
    Marker,
    Redaction,
    StepBadge,
    StepShape,
    TextAlign,
    TextLabel,
)
from core.annotate.palette import BRAND_PALETTE, PALETTE_LABELS
from core.annotate.primitives import doc_scale
from core.annotate.style import (
    CARD_FILL,
    DEFAULT_LENS_CORNER,
    DEFAULT_LENS_FRAME_WIDTH,
    HIGHLIGHT_MARKER_OPACITY,
    HIGHLIGHT_OVERLAY_OPACITY,
    HIGHLIGHT_RADIUS,
    HIGHLIGHT_SWATCHES,
    MARKER_STROKE,
    MAX_HIGHLIGHT_RADIUS,
    MAX_LENS_FRAME_WIDTH,
    MAX_LENS_PART_WIDTH,
    MAX_LINE_WIDTH,
    MAX_NUMBER_SIZE,
    MAX_SCALE,
    MAX_STEP_SIZE,
    MAX_STEP_STROKE,
    MIN_LENS_FRAME_WIDTH,
    MIN_LENS_PART_WIDTH,
    MIN_LINE_WIDTH,
    MIN_NUMBER_SIZE,
    MIN_SCALE,
    MIN_STEP_SIZE,
    MIN_STEP_STROKE,
    STEP_RADIUS,
    STEP_STROKE,
    TEXT_PRESETS,
)
from ui.annotate.controller import DEFAULT_REDACTION_BLOCK, EditController, Tool
from ui.widgets import ColorPickerButton, ColorSwatchRow

ARROW_LABELS = {
    ArrowSide.AUTO: "Automatica",
    ArrowSide.LEFT: "Izquierda",
    ArrowSide.RIGHT: "Derecha",
    ArrowSide.TOP: "Arriba",
    ArrowSide.BOTTOM: "Abajo",
    ArrowSide.NONE: "Sin flecha",
}
ALIGN_LABELS = {TextAlign.LEFT: "Izquierda", TextAlign.CENTER: "Centrada"}
LINE_STYLE_LABELS = {
    LineStyle.SOLID: "Continua",
    LineStyle.DASHED: "De rayas",
    LineStyle.DOTTED: "De puntos",
    LineStyle.DASH_DOT: "Raya y punto",
}
HEAD_LABELS = {HeadStyle.NONE: "Sin punta", HeadStyle.ARROW: "Flecha", HeadStyle.DOT: "Punto"}
STEP_SHAPE_LABELS = {
    StepShape.CIRCLE: "Circulo",
    StepShape.SQUARE: "Cuadrado",
    StepShape.ROUNDED: "Cuadrado redondeado",
    StepShape.DIAMOND: "Rombo",
}
LENS_SHAPE_LABELS = {
    LensShape.CIRCLE: "Circular",
    LensShape.ELLIPSE: "Ovalada",
    LensShape.ROUNDED: "Rectangular",
}
HIGHLIGHT_MODE_LABELS = {
    HighlightMode.MARKER: "Marcador",
    HighlightMode.OVERLAY: "Translucido",
}
PRESET_LABELS = {"nota": "Nota", "exito": "Exito", "alerta": "Alerta", "libre": "Libre (con contorno)"}

(_PAGE_EMPTY, _PAGE_MARKER, _PAGE_ARROW, _PAGE_STEP, _PAGE_TEXT, _PAGE_REDACTION, _PAGE_LENS,
 _PAGE_CROP, _PAGE_HIGHLIGHT) = range(9)


RESET_TIP = "Doble clic para restablecer el valor por defecto"
_TEXT_DEFAULT_SIZE = 28.0


class _ResetLabel(QLabel):
    """Etiqueta de un control: con doble clic lo devuelve a su valor por defecto (como en
    DaVinci Resolve)."""

    doubleClicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setToolTip(RESET_TIP)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.doubleClicked.emit()


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
        self._resets: list[tuple[QToolButton, Callable[[], bool]]] = []
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
        self._pages.addWidget(self._build_crop_page())
        self._pages.addWidget(self._build_highlight_page())

        # la pagina de la lupa es larga: el panel tiene scroll cuando la ventana es baja
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._pages)
        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._scroll, stretch=1)

        controller.selectionChanged.connect(self.sync)
        controller.toolChanged.connect(lambda _tool: self.sync())
        controller.cropDraftChanged.connect(self._update_crop_size)
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
        self._crop_info = QLabel()
        self._crop_info.setWordWrap(True)
        self._crop_remove = QPushButton("Quitar recorte")
        self._crop_remove.clicked.connect(lambda: self._c.set_crop(None))
        self._clip_notice = QLabel()
        self._clip_notice.setWordWrap(True)
        self._clip_notice.setStyleSheet("color: #E8B95C;")
        self._clip_btn = QPushButton()
        self._clip_btn.clicked.connect(self._on_add_padding_clicked)
        self._reset_row(form, "Margen extra", self._padding_spin,
                        lambda: self._c.set_padding(0), lambda: self._c.doc is None or self._c.doc.padding == 0)
        form.addRow(self._scale_auto)
        self._reset_row(form, "Escala de trazo", self._scale_spin,
                        lambda: self._c.set_style_scale(None),
                        lambda: self._c.doc is None or self._c.doc.style_scale is None)
        form.addRow(self._crop_info)
        form.addRow(self._crop_remove)
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
            reset_label = _ResetLabel(label)
            reset_label.doubleClicked.connect(lambda k=key: self._on_palette_color(k, getattr(BRAND_PALETTE, k)))
            colors_form.addRow(reset_label, picker)
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

    def _reset_row(
        self,
        form: QFormLayout,
        text: str,
        control: QWidget,
        reset: Callable[[], None],
        is_default: Callable[[], bool],
    ) -> QWidget:
        """Fila de un control con su valor por defecto: doble clic en la etiqueta o el boton
        "restablecer" (que solo se activa si el valor ya no es el de fabrica). Devuelve el
        contenedor de la fila (para mostrarla u ocultarla)."""
        label = _ResetLabel(text)
        label.doubleClicked.connect(reset)
        button = QToolButton()
        button.setText("↺")
        button.setToolTip("Restablecer el valor por defecto")
        button.clicked.connect(reset)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(control, stretch=1)
        layout.addWidget(button)
        form.addRow(label, container)
        self._resets.append((button, is_default))
        return container

    def _field_row(self, form: QFormLayout, text: str, control: QWidget, field: str, default) -> QWidget:
        """_reset_row para un campo de la anotacion seleccionada; `default` puede ser una
        funcion (cuando el valor de fabrica depende del documento)."""

        def value():
            return default() if callable(default) else default

        def reset() -> None:
            self._c.edit_selected(_merge=False, **{field: value()})   # restablecer es su propio paso

        def is_default() -> bool:
            item = self._c.selected_item()
            return item is None or not hasattr(item, field) or getattr(item, field) == value()

        return self._reset_row(form, text, control, reset, is_default)

    def _fit_page_size(self) -> None:
        """El panel mide lo que la pagina visible (no la mas alta de todas): las demas no cuentan."""
        current = self._pages.currentWidget()
        for index in range(self._pages.count()):
            page = self._pages.widget(index)
            policy = QSizePolicy.Preferred if page is current else QSizePolicy.Ignored
            page.setSizePolicy(policy, policy)
        self._pages.updateGeometry()

    def _refresh_resets(self) -> None:
        for button, is_default in self._resets:
            button.setEnabled(not is_default())

    def _color_row(self, form: QFormLayout, label: str, field: str) -> _ColorRow:
        """Fila de color de una anotacion: el campo `field` (None = el de la paleta)."""
        row = _ColorRow()
        row.changed.connect(lambda value, f=field: self._apply_color(f, value))
        reset_label = _ResetLabel(label)
        reset_label.doubleClicked.connect(lambda f=field: self._apply_color(f, None))
        form.addRow(reset_label, row)
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

    def _build_crop_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            "Arrastra sobre la captura para elegir lo que se queda, o mueve las asas del "
            "recuadro. Se puede deshacer; la imagen original no se toca."
        )
        hint.setWordWrap(True)
        self._crop_size = QLabel()
        self._crop_outside = QLabel()
        self._crop_outside.setWordWrap(True)
        self._crop_outside.setStyleSheet("color: #E8B95C;")
        self._crop_remove_tool = QPushButton("Quitar recorte")
        self._crop_remove_tool.clicked.connect(lambda: self._c.set_crop(None))
        done = QPushButton("Listo")
        done.setToolTip("Vuelve a Seleccionar (Esc)")
        done.clicked.connect(lambda: self._c.set_tool(Tool.SELECT))
        for widget in (hint, self._crop_size, self._crop_outside, self._crop_remove_tool, done):
            layout.addWidget(widget)
        layout.addStretch(1)
        return page

    def _highlight_default_opacity(self) -> float:
        """Intensidad de fabrica del resaltador seleccionado: depende de su modo."""
        item = self._c.selected_item()
        if isinstance(item, Highlight) and item.mode is HighlightMode.OVERLAY:
            return HIGHLIGHT_OVERLAY_OPACITY
        return HIGHLIGHT_MARKER_OPACITY

    def _on_highlight_mode(self) -> None:
        """Cambiar de modo ajusta tambien la intensidad (en un solo paso): el modo Translucido
        necesita menos que el Marcador para que se lea el texto."""
        mode = HighlightMode(self._hl_mode.currentData())
        opacity = HIGHLIGHT_OVERLAY_OPACITY if mode is HighlightMode.OVERLAY else HIGHLIGHT_MARKER_OPACITY
        if not self._syncing:
            self._c.edit_selected(_merge=False, mode=mode, opacity=opacity)

    def _reset_highlight_mode(self) -> None:
        self._c.edit_selected(_merge=False, mode=HighlightMode.MARKER, opacity=HIGHLIGHT_MARKER_OPACITY)

    def _build_highlight_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._hl_swatches = ColorSwatchRow(HIGHLIGHT_SWATCHES)
        self._hl_swatches.colorPicked.connect(lambda color: self._apply_color("color", color))
        form.addRow("Estandar", self._hl_swatches)
        self._hl_color = self._color_row(form, "Personalizado", "color")
        self._hl_mode = QComboBox()
        for mode, label in HIGHLIGHT_MODE_LABELS.items():
            self._hl_mode.addItem(label, mode.value)
        self._hl_mode.currentIndexChanged.connect(lambda _i: self._on_highlight_mode())
        self._reset_row(
            form, "Modo", self._hl_mode, self._reset_highlight_mode,
            lambda: not isinstance(self._c.selected_item(), Highlight)
            or (self._c.selected_item().mode is HighlightMode.MARKER
                and self._c.selected_item().opacity == HIGHLIGHT_MARKER_OPACITY),
        )
        note = QLabel(
            "Marcador mezcla el color con lo de abajo y deja el texto negro: es para capturas claras. "
            "En capturas oscuras usa Translucido."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self._hl_opacity = QSpinBox()
        self._hl_opacity.setRange(5, 100)
        self._hl_opacity.setSuffix(" %")
        self._hl_opacity.valueChanged.connect(lambda v: self._apply(opacity=v / 100))
        self._field_row(form, "Intensidad", self._hl_opacity, "opacity", self._highlight_default_opacity)
        self._hl_radius = QDoubleSpinBox()
        self._hl_radius.setRange(0.0, MAX_HIGHLIGHT_RADIUS)
        self._hl_radius.setSingleStep(0.5)
        self._hl_radius.setDecimals(1)
        self._hl_radius.setSuffix(" px")
        self._hl_radius.setToolTip("Esquinas redondeadas del resaltador")
        self._hl_radius.valueChanged.connect(lambda v: self._apply(radius=float(v)))
        self._field_row(form, "Esquinas", self._hl_radius, "radius", HIGHLIGHT_RADIUS)
        return page

    def _reset_marker_arrow(self) -> None:
        self._c.edit_selected(_merge=False, arrow=ArrowSide.AUTO, arrow_start=None, arrow_tip=None)

    def _build_marker_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._marker_arrow = QComboBox()
        for side, label in ARROW_LABELS.items():
            self._marker_arrow.addItem(label, side.value)
        # elegir un lado es pedir la flecha AUTOMATICA de ese lado: suelta la que se movio a mano
        self._marker_arrow.currentIndexChanged.connect(
            lambda _i: self._apply(
                arrow=ArrowSide(self._marker_arrow.currentData()), arrow_start=None, arrow_tip=None
            )
        )
        self._marker_glow = QCheckBox("Resplandor")
        self._marker_glow.toggled.connect(lambda on: self._apply(glow=on))
        self._reset_row(
            form, "Lado de la flecha", self._marker_arrow, self._reset_marker_arrow,
            lambda: not isinstance(self._c.selected_item(), Marker)
            or (self._c.selected_item().arrow is ArrowSide.AUTO and not self._c.selected_item().custom_arrow),
        )
        hint = QLabel("Arrastra la punta o la cola de la flecha para alargarla, acortarla o girarla; "
                      "arrastra su cuerpo para moverla.")
        hint.setWordWrap(True)
        self._marker_arrow_hint = hint
        form.addRow(hint)
        self._marker_arrow_reset = QPushButton("Recolocar flecha")
        self._marker_arrow_reset.setToolTip("Devuelve la flecha a la posicion automatica de su lado")
        self._marker_arrow_reset.clicked.connect(self._c.auto_place_selected_arrow)
        form.addRow(self._marker_arrow_reset)
        form.addRow(self._marker_glow)
        self._marker_stroke = self._color_row(form, "Recuadro", "stroke_color")
        self._marker_arrow_color = self._color_row(form, "Flecha", "arrow_color")
        self._marker_glow_color = self._color_row(form, "Resplandor", "glow_color")
        return page

    def _build_arrow_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._arrow_head_start = self._head_combo("head_start")
        self._field_row(form, "Punta inicial", self._arrow_head_start, "head_start", HeadStyle.NONE)
        self._arrow_head_end = self._head_combo("head_end")
        self._field_row(form, "Punta final", self._arrow_head_end, "head_end", HeadStyle.ARROW)
        self._arrow_style = QComboBox()
        for line_style, label in LINE_STYLE_LABELS.items():
            self._arrow_style.addItem(label, line_style.value)
        self._arrow_style.currentIndexChanged.connect(
            lambda _i: self._apply(line_style=LineStyle(self._arrow_style.currentData()))
        )
        self._field_row(form, "Estilo", self._arrow_style, "line_style", LineStyle.SOLID)
        self._arrow_width = QDoubleSpinBox()
        self._arrow_width.setRange(MIN_LINE_WIDTH, MAX_LINE_WIDTH)
        self._arrow_width.setDecimals(1)
        self._arrow_width.setSingleStep(0.5)
        self._arrow_width.setSuffix(" px")
        self._arrow_width.valueChanged.connect(lambda v: self._apply(width=float(v)))
        self._field_row(form, "Grosor", self._arrow_width, "width", MARKER_STROKE)
        self._arrow_glow = QCheckBox("Resplandor")
        self._arrow_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow(self._arrow_glow)
        self._arrow_color = self._color_row(form, "Color", "color")
        self._arrow_glow_color = self._color_row(form, "Resplandor", "glow_color")
        return page

    def _head_combo(self, field: str) -> QComboBox:
        combo = QComboBox()
        for head, label in HEAD_LABELS.items():
            combo.addItem(label, head.value)
        combo.currentIndexChanged.connect(lambda _i: self._apply(**{field: HeadStyle(combo.currentData())}))
        return combo

    def _build_step_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._step_number = QSpinBox()
        self._step_number.setRange(1, 999)
        self._step_number.valueChanged.connect(lambda v: self._apply(number=v))
        form.addRow("Numero", self._step_number)
        self._step_shape = QComboBox()
        for shape, label in STEP_SHAPE_LABELS.items():
            self._step_shape.addItem(label, shape.value)
        self._step_shape.currentIndexChanged.connect(
            lambda _i: self._apply(shape=StepShape(self._step_shape.currentData()))
        )
        self._field_row(form, "Forma", self._step_shape, "shape", StepShape.CIRCLE)
        self._step_color = self._color_row(form, "Borde", "color")
        self._step_fill = self._color_row(form, "Relleno", "fill_color")
        self._step_number_color = self._color_row(form, "Color numero", "number_color")
        self._step_size = QDoubleSpinBox()
        self._step_size.setRange(MIN_STEP_SIZE, MAX_STEP_SIZE)
        self._step_size.setDecimals(1)
        self._step_size.setSingleStep(1.0)
        self._step_size.setSuffix(" px")
        self._step_size.setToolTip("Radio del paso (la mitad de su ancho)")
        self._step_size.valueChanged.connect(lambda v: self._apply(size=float(v)))
        self._field_row(form, "Tamano", self._step_size, "size", STEP_RADIUS)
        self._step_number_size = QDoubleSpinBox()
        self._step_number_size.setRange(0.0, MAX_NUMBER_SIZE)
        self._step_number_size.setDecimals(1)
        self._step_number_size.setSingleStep(1.0)
        self._step_number_size.setSuffix(" px")
        self._step_number_size.setSpecialValueText("Auto")
        self._step_number_size.setToolTip("Auto = proporcional al tamano del paso")
        self._step_number_size.valueChanged.connect(lambda v: self._apply(number_size=max(float(v), MIN_NUMBER_SIZE) if v > 0 else None))
        self._field_row(form, "Tam. numero", self._step_number_size, "number_size", None)
        self._step_stroke = QDoubleSpinBox()
        self._step_stroke.setRange(MIN_STEP_STROKE, MAX_STEP_STROKE)
        self._step_stroke.setDecimals(1)
        self._step_stroke.setSingleStep(0.5)
        self._step_stroke.setSuffix(" px")
        self._step_stroke.valueChanged.connect(lambda v: self._apply(border_width=float(v)))
        self._field_row(form, "Grosor borde", self._step_stroke, "border_width", STEP_STROKE)
        self._step_glow = QCheckBox("Resplandor")
        self._step_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow(self._step_glow)
        self._step_form = form
        self._step_glow_color = self._color_row(form, "Color", "glow_color")
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
        self._field_row(form, "Tamano", self._text_size, "size", _TEXT_DEFAULT_SIZE)
        form.addRow(self._text_bold)
        self._field_row(form, "Alineacion", self._text_align, "align", TextAlign.LEFT)
        return page

    def _build_redaction_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._redaction_block = QSpinBox()
        self._redaction_block.setRange(2, 200)
        self._redaction_block.valueChanged.connect(lambda v: self._apply(block=v))
        self._field_row(form, "Tamano del bloque", self._redaction_block, "block",
                        lambda: max(6, round(DEFAULT_REDACTION_BLOCK * self._c.scale())))
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
        self._field_row(form, "Zoom", self._lens_zoom, "zoom", 2.0)
        form.addRow(self._lens_warning)
        self._field_row(form, "Forma", self._lens_shape, "shape", LensShape.CIRCLE)
        self._lens_corner = QSpinBox()
        self._lens_corner.setRange(0, 50)
        self._lens_corner.setSuffix(" %")
        self._lens_corner.setToolTip("0 = esquinas rectas; 50 = tan redondeadas que parece una capsula")
        self._lens_corner.valueChanged.connect(lambda v: self._apply(corner=v / 100))
        self._lens_corner_row = self._field_row(form, "Esquinas", self._lens_corner, "corner", DEFAULT_LENS_CORNER)
        self._lens_form = form
        form.addRow(self._lens_connector)

        self._section(form, "Marco del lente")
        self._lens_frame = self._color_row(form, "Color", "frame_color")
        self._lens_frame_width = QDoubleSpinBox()
        self._lens_frame_width.setRange(MIN_LENS_FRAME_WIDTH, MAX_LENS_FRAME_WIDTH)
        self._lens_frame_width.setSingleStep(0.5)
        self._lens_frame_width.setDecimals(1)
        self._lens_frame_width.setSuffix(" px")
        self._lens_frame_width.setToolTip("Grosor del borde del lente; en la zona de origen y el conector, Auto = la mitad")
        self._lens_frame_width.valueChanged.connect(lambda v: self._apply(frame_width=float(v)))
        self._field_row(form, "Grosor", self._lens_frame_width, "frame_width", DEFAULT_LENS_FRAME_WIDTH)
        self._lens_frame_style = self._line_style_combo("frame_style")
        self._field_row(form, "Estilo", self._lens_frame_style, "frame_style", LineStyle.SOLID)

        self._section(form, "Zona de origen")
        self._lens_source_color = self._color_row(form, "Color", "source_color")
        self._lens_source_width = self._part_width_spin("source_width")
        self._field_row(form, "Grosor", self._lens_source_width, "source_width", None)
        self._lens_source_style = self._line_style_combo("source_style")
        self._field_row(form, "Estilo", self._lens_source_style, "source_style", LineStyle.DASHED)

        self._lens_connector_header = self._section(form, "Conector")
        self._lens_connector_color = self._color_row(form, "Color", "connector_color")
        self._lens_connector_width = self._part_width_spin("connector_width")
        self._lens_connector_width_row = self._field_row(form, "Grosor", self._lens_connector_width, "connector_width", None)
        self._lens_connector_style = self._line_style_combo("connector_style")
        self._lens_connector_style_row = self._field_row(form, "Estilo", self._lens_connector_style, "connector_style", LineStyle.SOLID)

        self._section(form, "Resplandor")
        self._lens_glow = QCheckBox("Resplandor")
        self._lens_glow.toggled.connect(lambda on: self._apply(glow=on))
        form.addRow(self._lens_glow)
        self._lens_glow_color = self._color_row(form, "Color", "glow_color")
        form.addRow(replace_btn)
        return page

    @staticmethod
    def _section(form: QFormLayout, text: str) -> QLabel:
        """Titulo de un grupo de controles dentro de un formulario."""
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setContentsMargins(0, 8, 0, 0)
        form.addRow(label)
        return label

    def _line_style_combo(self, field: str) -> QComboBox:
        combo = QComboBox()
        for line_style, label in LINE_STYLE_LABELS.items():
            combo.addItem(label, line_style.value)
        combo.currentIndexChanged.connect(lambda _i: self._apply(**{field: LineStyle(combo.currentData())}))
        return combo

    def _part_width_spin(self, field: str) -> QDoubleSpinBox:
        """Grosor propio de una parte de la lupa; 0 = Auto (la mitad del grosor del marco)."""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, MAX_LENS_PART_WIDTH)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" px")
        spin.setSpecialValueText("Auto")
        spin.setToolTip("Auto = la mitad del grosor del marco del lente")
        spin.valueChanged.connect(
            lambda v: self._apply(**{field: max(float(v), MIN_LENS_PART_WIDTH) if v > 0 else None})
        )
        return spin

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
            if self._c.tool is Tool.CROP and self._c.doc is not None:
                self._pages.setCurrentIndex(_PAGE_CROP)
                self._title.setText("Recortar")
            elif isinstance(item, Marker):
                self._pages.setCurrentIndex(_PAGE_MARKER)
                self._title.setText("Marcador")
                self._set_combo(self._marker_arrow, item.arrow.value)
                self._marker_arrow_reset.setVisible(item.custom_arrow)
                self._marker_arrow_hint.setVisible(item.arrow is not ArrowSide.NONE)
                self._marker_glow.setChecked(item.glow)
                self._marker_stroke.set_value(item.stroke_color or pal.marker, item.stroke_color is not None)
                self._marker_arrow_color.set_value(item.arrow_color or pal.arrow, item.arrow_color is not None)
                self._marker_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
            elif isinstance(item, Arrow):
                self._pages.setCurrentIndex(_PAGE_ARROW)
                self._title.setText(
                    "Linea" if item.head_start is HeadStyle.NONE and item.head_end is HeadStyle.NONE else "Flecha"
                )
                self._set_combo(self._arrow_head_start, item.head_start.value)
                self._set_combo(self._arrow_head_end, item.head_end.value)
                self._set_combo(self._arrow_style, item.line_style.value)
                if abs(self._arrow_width.value() - item.width) > 1e-9:
                    self._arrow_width.setValue(item.width)
                self._arrow_glow.setChecked(item.glow)
                self._arrow_color.set_value(item.color or pal.arrow, item.color is not None)
                self._arrow_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
            elif isinstance(item, StepBadge):
                self._pages.setCurrentIndex(_PAGE_STEP)
                self._title.setText("Paso numerado")
                if self._step_number.value() != item.number:
                    self._step_number.setValue(item.number)
                self._step_color.set_value(item.color or pal.step, item.color is not None)
                self._set_combo(self._step_shape, item.shape.value)
                self._step_fill.set_value(item.fill_color or CARD_FILL, item.fill_color is not None)
                self._step_number_color.set_value(
                    item.number_color or item.color or pal.step, item.number_color is not None
                )
                if abs(self._step_size.value() - item.size) > 1e-9:
                    self._step_size.setValue(item.size)
                number_size = item.number_size or 0.0
                if abs(self._step_number_size.value() - number_size) > 1e-9:
                    self._step_number_size.setValue(number_size)
                if abs(self._step_stroke.value() - item.border_width) > 1e-9:
                    self._step_stroke.setValue(item.border_width)
                self._step_glow.setChecked(item.glow)
                self._step_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
                self._step_form.setRowVisible(self._step_glow_color, item.glow)
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
                self._lens_form.setRowVisible(self._lens_corner_row, item.shape is LensShape.ROUNDED)
                self._lens_connector.setChecked(item.connector)
                self._lens_frame.set_value(item.frame_color or pal.lens, item.frame_color is not None)
                if abs(self._lens_frame_width.value() - item.frame_width) > 1e-9:
                    self._lens_frame_width.setValue(item.frame_width)
                self._set_combo(self._lens_frame_style, item.frame_style.value)
                inherited = item.frame_color or pal.lens   # origen y conector sin color propio siguen al marco
                self._lens_source_color.set_value(item.source_color or inherited, item.source_color is not None)
                self._set_spin(self._lens_source_width, item.source_width or 0.0)
                self._set_combo(self._lens_source_style, item.source_style.value)
                self._lens_connector_color.set_value(item.connector_color or inherited, item.connector_color is not None)
                self._set_spin(self._lens_connector_width, item.connector_width or 0.0)
                self._set_combo(self._lens_connector_style, item.connector_style.value)
                for row in (self._lens_connector_header, self._lens_connector_color,
                            self._lens_connector_width_row, self._lens_connector_style_row):
                    self._lens_form.setRowVisible(row, item.connector)
                self._lens_glow.setChecked(item.glow)
                self._lens_glow_color.set_value(item.glow_color or pal.glow, item.glow_color is not None)
                self._lens_form.setRowVisible(self._lens_glow_color, item.glow)
            elif isinstance(item, Highlight):
                self._pages.setCurrentIndex(_PAGE_HIGHLIGHT)
                self._title.setText("Resaltador")
                effective = item.color or pal.highlight
                self._hl_color.set_value(effective, item.color is not None)
                self._hl_swatches.set_current(effective)
                self._set_combo(self._hl_mode, item.mode.value)
                if self._hl_opacity.value() != round(item.opacity * 100):
                    self._hl_opacity.setValue(round(item.opacity * 100))
                if abs(self._hl_radius.value() - item.radius) > 1e-9:
                    self._hl_radius.setValue(item.radius)
            elif isinstance(item, Redaction):
                self._pages.setCurrentIndex(_PAGE_REDACTION)
                self._title.setText("Pixelado")
                if self._redaction_block.value() != item.block:
                    self._redaction_block.setValue(item.block)
            else:
                self._pages.setCurrentIndex(_PAGE_EMPTY)
                self._title.setText("Propiedades")
            self._sync_document()
            self._refresh_resets()
            self._fit_page_size()
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
        self._sync_crop(doc)
        clipped = needed > doc.padding
        self._clip_notice.setVisible(clipped)
        self._clip_btn.setVisible(clipped)
        if clipped:
            self._clip_notice.setText("El resplandor o alguna etiqueta se recorta en el borde de la captura.")
            self._clip_btn.setText(f"Agregar margen de {needed} px")

    def _sync_crop(self, doc) -> None:
        """Datos del recorte: en la pagina del documento y en la de la herramienta Recortar."""
        crop = doc.crop
        on_page = self._pages.currentIndex() in (_PAGE_EMPTY, _PAGE_CROP)
        outside = items_outside_view(doc) if crop is not None and on_page else []
        warning = f"{len(outside)} anotacion(es) quedan fuera del recorte y no se exportan." if outside else ""
        view = doc.view
        info = f"Recorte: {int(view.w)} x {int(view.h)} px"
        self._crop_info.setText(f"{info}\n{warning}" if warning else info)
        self._crop_info.setVisible(crop is not None and self._pages.currentIndex() == _PAGE_EMPTY)
        self._crop_remove.setVisible(crop is not None)
        self._crop_remove_tool.setEnabled(crop is not None)
        self._crop_outside.setText(warning)
        self._crop_outside.setVisible(bool(warning))
        self._update_crop_size()

    def _update_crop_size(self) -> None:
        """Tamano del recuadro de recorte, en vivo mientras se arrastra."""
        doc = self._c.doc
        rect = self._c.crop_rect()
        if doc is None or rect is None:
            return
        shown = rect if self._c.crop_draft is not None or doc.crop is not None else None
        self._crop_size.setText(
            f"{int(rect.w)} x {int(rect.h)} px" if shown else "Sin recorte (imagen completa)"
        )

    @staticmethod
    def _set_spin(spin: QDoubleSpinBox, value: float) -> None:
        if abs(spin.value() - value) > 1e-9:
            spin.setValue(value)

    @staticmethod
    def _set_combo(combo: QComboBox, data: str) -> None:
        index = combo.findData(data)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
