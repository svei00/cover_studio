"""Ventana principal de Cover Studio."""

from __future__ import annotations

import copy
import re
import shutil
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QFontMetricsF, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFontComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.brand import default_cover_config, load_brand, save_brand
from core.geometry import (
    MAX_SUBTITLE_BORDER,
    CanvasSize,
    CoverConfig,
    FontWeight,
    GeometryError,
    GradientDirection,
    Orientation,
    SubtitleLayout,
    SubtitlePosition,
    VerticalPosition,
    build_svg,
    compute_band_geometry,
    compute_subtitle_layout,
    render_png,
)
from core.presets import PresetError, list_presets, load_preset, save_preset
from core.text_utils import normalize_title, wrap_title
from core.user_settings import UserSettingsError
from ui.annotate.tab import AnnotateTab
from ui.brand_dialog import BrandDialog
from ui.dialogs import OverwriteConfirmDialog
from ui.preview import PreviewWidget
from ui.widgets import ColorPickerButton, SliderSpinBox

PREVIEW_DEBOUNCE_MS = 250

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"
SUPPORTED_PHOTO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

CANVAS_PRESETS: dict[str, CanvasSize | None] = {
    "1920 x 1080 (16:9)": CanvasSize(1920, 1080),
    "1080 x 1350 (4:5)": CanvasSize(1080, 1350),
    "1080 x 1080 (1:1)": CanvasSize(1080, 1080),
    "1200 x 630 (Open Graph)": CanvasSize(1200, 630),
    "Personalizado": None,
}

ORIENTATION_LABELS: dict[Orientation, str] = {
    Orientation.BOTTOM_RIGHT: "Abajo-derecha",
    Orientation.BOTTOM_LEFT: "Abajo-izquierda",
    Orientation.TOP_RIGHT: "Arriba-derecha",
    Orientation.TOP_LEFT: "Arriba-izquierda",
}

SUBTITLE_POSITION_LABELS: dict[SubtitlePosition, str] = {
    SubtitlePosition.BOTTOM_RIGHT: "Abajo-derecha",
    SubtitlePosition.BOTTOM_LEFT: "Abajo-izquierda",
    SubtitlePosition.BOTTOM_CENTER: "Abajo-centro",
}

GRADIENT_DIRECTION_LABELS: dict[GradientDirection, str] = {
    GradientDirection.HORIZONTAL: "Horizontal (izq. a der.)",
    GradientDirection.VERTICAL: "Vertical (arriba a abajo)",
    GradientDirection.DIAGONAL: "Diagonal",
}

VERTICAL_LABELS: dict[VerticalPosition, str] = {
    VerticalPosition.TOP: "Arriba",
    VerticalPosition.CENTER: "Centro",
    VerticalPosition.BOTTOM: "Abajo",
}


def _slugify_for_filename(text: str) -> str:
    """Convierte un titulo a un slug seguro para nombre de archivo."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "cover"


def _make_collapsible_group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    """QGroupBox marcable que colapsa su contenido al destildarse."""
    box = QGroupBox(title)
    box.setCheckable(True)
    box.setChecked(True)
    inner = QWidget()
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(4, 4, 4, 4)
    outer_layout = QVBoxLayout(box)
    outer_layout.addWidget(inner)
    box.toggled.connect(inner.setVisible)
    return box, inner_layout


def _row(label_text: str, widget: QWidget) -> QWidget:
    """Fila horizontal etiqueta + widget, para meter en un layout vertical."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(label_text)
    label.setMinimumWidth(150)
    layout.addWidget(label)
    layout.addWidget(widget, stretch=1)
    return container


class MainWindow(QMainWindow):
    """Ventana principal: entradas, panel de diseno, vista previa y generacion."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Cover Studio — {load_brand().name}")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self.config = default_cover_config()
        self.photo_path: Path | None = None
        self.output_manually_edited = False
        self.last_output_path: Path | None = None
        self._generated_signature: tuple | None = None   # el contenido y diseno de la ultima portada generada
        self._syncing_subtitle_position = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._trigger_preview_render)

        self._build_ui()
        self._apply_config_to_widgets(self.config)
        self._refresh_preset_combo()

    # ------------------------------------------------------------------
    # Construccion de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        cover_page = QWidget()
        root_layout = QVBoxLayout(cover_page)

        root_layout.addLayout(self._build_preset_bar())

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_preview_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.annotate_tab = AnnotateTab()
        self.annotate_tab.statusMessage.connect(self.statusBar().showMessage)
        self.annotate_tab.dirtyChanged.connect(self._on_annotate_dirty_changed)
        self.annotate_tab.panel.editBrandRequested.connect(self._on_edit_brand_clicked)

        self.tabs = QTabWidget()
        self.tabs.addTab(cover_page, "Portada")
        self.tabs.addTab(self.annotate_tab, "Anotar")
        self.setCentralWidget(self.tabs)

        self._connect_preview_triggers()
        self.statusBar().showMessage("Listo.")

    def _on_annotate_dirty_changed(self, dirty: bool) -> None:
        index = self.tabs.indexOf(self.annotate_tab)
        self.tabs.setTabText(index, "Anotar *" if dirty else "Anotar")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.annotate_tab.confirm_discard():
            super().closeEvent(event)
        else:
            event.ignore()

    def _connect_preview_triggers(self) -> None:
        """Cualquier control que cambie el diseno o el contenido debe
        reprogramar la vista previa en vivo (con debounce)."""
        triggers = [
            self.title_edit.textChanged,
            self.subtitle_edit.textChanged,
            self.subtitle_position_combo.currentIndexChanged,
            self.subtitle_text_color_picker.colorChanged,
            self.subtitle_bg_color_picker.colorChanged,
            self.subtitle_opacity_slider.valueChanged,
            self.subtitle_border_color_picker.colorChanged,
            self.subtitle_border_slider.valueChanged,
            self.subtitle_font_slider.valueChanged,
            self.subtitle_outline_checkbox.toggled,
            self.subtitle_outline_color_picker.colorChanged,
            self.subtitle_gradient_checkbox.toggled,
            self.subtitle_border_gradient_checkbox.toggled,
            self.subtitle_border_color2_picker.colorChanged,
            self.subtitle_bg_color2_picker.colorChanged,
            self.subtitle_gradient_direction_combo.currentIndexChanged,
            self.band_color_picker.colorChanged,
            self.accent_color_picker.colorChanged,
            self.text_color_picker.colorChanged,
            self.outline_color_picker.colorChanged,
            self.outline_checkbox.toggled,
            self.band_opacity_slider.valueChanged,
            self.accent_opacity_independent_checkbox.toggled,
            self.accent_opacity_slider.valueChanged,
            self.orientation_combo.currentIndexChanged,
            self.accent_shift_slider.valueChanged,
            self.corner_radius_slider.valueChanged,
            self.band_height_slider.valueChanged,
            self.band_margin_left_slider.valueChanged,
            self.band_margin_top_slider.valueChanged,
            self.band_width_manual_checkbox.toggled,
            self.band_width_slider.valueChanged,
            self.vertical_position_combo.currentIndexChanged,
            self.font_combo.currentFontChanged,
            self.font_size_slider.valueChanged,
            self.auto_fit_checkbox.toggled,
            self.weight_combo.currentIndexChanged,
            self.shadow_checkbox.toggled,
            self.shadow_intensity_slider.valueChanged,
            self.max_lines_spin.valueChanged,
            self.canvas_combo.currentTextChanged,
            self.canvas_width_spin.valueChanged,
            self.canvas_height_spin.valueChanged,
        ]
        for signal in triggers:
            signal.connect(self._schedule_preview_update)

    def _build_preset_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.new_cover_btn = QPushButton("Nueva portada")
        self.new_cover_btn.setShortcut(QKeySequence("Ctrl+N"))
        self.new_cover_btn.setToolTip(
            "Empieza otra portada (Ctrl+N): borra el titulo, el subtitulo, la foto y la ruta de salida.\n"
            "El diseno actual se conserva; para volver a los valores de marca usa Restablecer todo."
        )
        self.new_cover_btn.clicked.connect(self._on_new_cover_clicked)
        layout.addWidget(self.new_cover_btn)
        layout.addSpacing(12)
        layout.addWidget(QLabel("Preset:"))

        self.preset_combo = QComboBox()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        layout.addWidget(self.preset_combo, stretch=1)

        save_preset_btn = QPushButton("Guardar preset")
        save_preset_btn.clicked.connect(self._on_save_preset_clicked)
        layout.addWidget(save_preset_btn)

        reset_btn = QPushButton("Restablecer todo")
        reset_btn.clicked.connect(self._on_reset_all_clicked)
        layout.addWidget(reset_btn)

        return layout

    def _build_left_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(490)   # el grupo Subtitulo (coordenadas y botones) pide ~460 px sin barra horizontal
        scroll.setMaximumWidth(540)

        container = QWidget()
        layout = QVBoxLayout(container)

        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_subtitle_group())
        layout.addWidget(self._build_colors_group())
        layout.addWidget(self._build_opacity_group())
        layout.addWidget(self._build_geometry_group())
        layout.addWidget(self._build_typography_group())
        layout.addWidget(self._build_canvas_group())
        layout.addWidget(self._build_output_group())
        layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_input_group(self) -> QWidget:
        box = QGroupBox("Contenido")
        layout = QVBoxLayout(box)

        layout.addWidget(QLabel("Titulo"))
        self.title_edit = QPlainTextEdit()
        self.title_edit.setMaximumHeight(70)
        self.title_edit.textChanged.connect(self._on_title_changed)
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Subtitulo (opcional)"))
        self.subtitle_edit = QLineEdit()
        self.subtitle_edit.setPlaceholderText("Vacio = sin subtitulo")
        layout.addWidget(self.subtitle_edit)

        photo_row = QWidget()
        photo_layout = QHBoxLayout(photo_row)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        self.photo_edit = QLineEdit()
        self.photo_edit.setPlaceholderText("Arrastra una foto aqui o usa Examinar…")
        self.photo_edit.setReadOnly(True)
        browse_btn = QPushButton("Examinar…")
        browse_btn.clicked.connect(self._on_browse_photo_clicked)
        photo_layout.addWidget(self.photo_edit, stretch=1)
        photo_layout.addWidget(browse_btn)
        layout.addWidget(QLabel("Foto de fondo"))
        layout.addWidget(photo_row)

        layout.addWidget(QLabel("Ruta de salida"))
        self.output_edit = QLineEdit()
        self.output_edit.textEdited.connect(self._on_output_manually_edited)
        layout.addWidget(self.output_edit)

        return box

    def _build_subtitle_group(self) -> QWidget:
        """Estilo de la franja del subtitulo (el texto se escribe en 'Contenido')."""
        box, layout = _make_collapsible_group("Subtitulo")

        self.subtitle_position_combo = QComboBox()
        for position, label in SUBTITLE_POSITION_LABELS.items():
            self.subtitle_position_combo.addItem(label, position)
        self.subtitle_position_combo.currentIndexChanged.connect(self._on_subtitle_position_changed)
        layout.addWidget(_row("Posicion", self.subtitle_position_combo))

        self.subtitle_reset_position_btn = QPushButton("Volver a la posicion automatica")
        self.subtitle_reset_position_btn.setToolTip(
            "El subtitulo se arrastra en la vista previa; esto lo devuelve a la posicion elegida arriba"
        )
        self.subtitle_reset_position_btn.setEnabled(False)
        self.subtitle_reset_position_btn.clicked.connect(self._on_subtitle_reset_position_clicked)
        layout.addWidget(self.subtitle_reset_position_btn)

        # coordenadas exactas (esquina superior izquierda, en px del lienzo): se anotan y se repiten
        self.subtitle_x_spin = QSpinBox()
        self.subtitle_y_spin = QSpinBox()
        coords = QWidget()
        coords_layout = QHBoxLayout(coords)
        coords_layout.setContentsMargins(0, 0, 0, 0)
        for text, spin in (("X", self.subtitle_x_spin), ("Y", self.subtitle_y_spin)):
            spin.setRange(0, 0)
            spin.setSuffix(" px")
            spin.setKeyboardTracking(False)   # al teclear una cifra de varios digitos, se aplica al terminar
            spin.setEnabled(False)
            coords_layout.addWidget(QLabel(text))
            coords_layout.addWidget(spin, stretch=1)
        self.subtitle_x_spin.setToolTip("Distancia de la esquina izquierda de la franja al borde izquierdo del lienzo")
        self.subtitle_y_spin.setToolTip("Distancia del borde superior de la franja al borde superior del lienzo")
        self.subtitle_x_spin.valueChanged.connect(self._on_subtitle_coordinate_edited)
        self.subtitle_y_spin.valueChanged.connect(self._on_subtitle_coordinate_edited)
        layout.addWidget(_row("Posicion exacta", coords))

        self.subtitle_step_spin = QSpinBox()
        self.subtitle_step_spin.setRange(1, 500)
        self.subtitle_step_spin.setValue(10)
        self.subtitle_step_spin.setSuffix(" px")
        nudge = QWidget()
        nudge_layout = QHBoxLayout(nudge)
        nudge_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_nudge_buttons: dict[str, QPushButton] = {}
        for key, symbol, tip, dx, dy in (
            ("left", "\u2190", "izquierda", -1, 0), ("right", "\u2192", "derecha", 1, 0),
            ("up", "\u2191", "arriba", 0, -1), ("down", "\u2193", "abajo", 0, 1),
        ):
            button = QPushButton(symbol)
            button.setToolTip(f"Mover el subtitulo hacia {tip}")
            button.setFixedWidth(30)   # compactos: cuatro botones de ancho normal no caben en el panel
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, ax=dx, ay=dy: self._nudge_subtitle(ax, ay))
            self.subtitle_nudge_buttons[key] = button
            nudge_layout.addWidget(button)
        nudge_layout.addWidget(QLabel("de a"))
        self.subtitle_step_spin.setMaximumWidth(92)
        nudge_layout.addWidget(self.subtitle_step_spin)
        nudge_layout.addStretch(1)
        layout.addWidget(_row("Mover", nudge))

        self.subtitle_text_color_picker = ColorPickerButton(self.config.subtitle_text_color)
        self.subtitle_text_color_picker.colorChanged.connect(self._on_subtitle_text_color_changed)
        layout.addWidget(_row("Color del texto", self.subtitle_text_color_picker))

        outline_row = QWidget()
        outline_layout = QHBoxLayout(outline_row)
        outline_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_outline_checkbox = QCheckBox("Contorno del texto")
        self.subtitle_outline_checkbox.toggled.connect(self._on_subtitle_outline_toggled)
        self.subtitle_outline_color_picker = ColorPickerButton(self.config.subtitle_outline_color)
        self.subtitle_outline_color_picker.colorChanged.connect(self._on_subtitle_outline_color_changed)
        self.subtitle_outline_color_picker.setEnabled(False)
        outline_layout.addWidget(self.subtitle_outline_checkbox)
        outline_layout.addWidget(self.subtitle_outline_color_picker, stretch=1)
        layout.addWidget(outline_row)

        self.subtitle_bg_color_picker = ColorPickerButton(self.config.subtitle_bg_color)
        self.subtitle_bg_color_picker.colorChanged.connect(self._on_subtitle_bg_color_changed)
        layout.addWidget(_row("Color de fondo", self.subtitle_bg_color_picker))

        # degradado de dos colores del RELLENO (por ahora bicolor): del color de fondo al segundo color
        self.subtitle_gradient_checkbox = QCheckBox("Degradado en el relleno")
        self.subtitle_gradient_checkbox.toggled.connect(self._on_subtitle_gradient_toggled)
        layout.addWidget(self.subtitle_gradient_checkbox)
        self.subtitle_gradient_panel = QWidget()
        gradient_layout = QVBoxLayout(self.subtitle_gradient_panel)
        gradient_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_bg_color2_picker = ColorPickerButton(self.config.subtitle_bg_color2)
        self.subtitle_bg_color2_picker.colorChanged.connect(self._on_subtitle_bg_color2_changed)
        gradient_layout.addWidget(_row("Segundo color", self.subtitle_bg_color2_picker))
        self.subtitle_gradient_panel.setVisible(False)
        layout.addWidget(self.subtitle_gradient_panel)

        self.subtitle_opacity_slider = SliderSpinBox(
            0, 100, round(self.config.subtitle_bg_opacity * 100), suffix="%"
        )
        self.subtitle_opacity_slider.setToolTip("Solo del relleno de la franja: el texto y el borde van al 100 %")
        self.subtitle_opacity_slider.valueChanged.connect(self._on_subtitle_opacity_changed)
        layout.addWidget(_row("Opacidad del fondo", self.subtitle_opacity_slider))

        self.subtitle_border_color_picker = ColorPickerButton(self.config.subtitle_border_color)
        self.subtitle_border_color_picker.colorChanged.connect(self._on_subtitle_border_color_changed)
        layout.addWidget(_row("Color del borde", self.subtitle_border_color_picker))

        # degradado de dos colores del BORDE: del color del borde al segundo color
        self.subtitle_border_gradient_checkbox = QCheckBox("Degradado en el borde")
        self.subtitle_border_gradient_checkbox.toggled.connect(self._on_subtitle_border_gradient_toggled)
        layout.addWidget(self.subtitle_border_gradient_checkbox)
        self.subtitle_border_gradient_panel = QWidget()
        border_gradient_layout = QVBoxLayout(self.subtitle_border_gradient_panel)
        border_gradient_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_border_color2_picker = ColorPickerButton(self.config.subtitle_border_color2)
        self.subtitle_border_color2_picker.colorChanged.connect(self._on_subtitle_border_color2_changed)
        border_gradient_layout.addWidget(_row("Segundo color", self.subtitle_border_color2_picker))
        self.subtitle_border_gradient_panel.setVisible(False)
        layout.addWidget(self.subtitle_border_gradient_panel)

        self.subtitle_border_slider = SliderSpinBox(
            0, MAX_SUBTITLE_BORDER, self.config.subtitle_border_width, step=0.5, suffix=" px", scale=10
        )
        self.subtitle_border_slider.setToolTip("0 = sin borde")
        self.subtitle_border_slider.valueChanged.connect(self._on_subtitle_border_width_changed)
        layout.addWidget(_row("Grosor del contorno", self.subtitle_border_slider))

        # controles comunes del degradado (relleno y borde): solo se ven si alguno esta encendido
        self.subtitle_gradient_common_panel = QWidget()
        common_layout = QVBoxLayout(self.subtitle_gradient_common_panel)
        common_layout.setContentsMargins(0, 0, 0, 0)
        self.subtitle_gradient_direction_combo = QComboBox()
        for direction, label in GRADIENT_DIRECTION_LABELS.items():
            self.subtitle_gradient_direction_combo.addItem(label, direction)
        self.subtitle_gradient_direction_combo.currentIndexChanged.connect(self._on_subtitle_gradient_direction_changed)
        common_layout.addWidget(_row("Direccion", self.subtitle_gradient_direction_combo))
        self.subtitle_brand_btn = QPushButton("Colores de marca (banda / acento)")
        self.subtitle_brand_btn.setToolTip(
            "Relleno: del color de la banda al del acento. Borde: del acento a la banda (al reves, para que se distinga)"
        )
        self.subtitle_brand_btn.clicked.connect(self._on_subtitle_brand_gradient_clicked)
        common_layout.addWidget(self.subtitle_brand_btn)
        self.subtitle_gradient_common_panel.setVisible(False)
        layout.addWidget(self.subtitle_gradient_common_panel)

        self.subtitle_font_slider = SliderSpinBox(12, 120, self.config.subtitle_font_size, suffix=" px")
        self.subtitle_font_slider.valueChanged.connect(self._on_subtitle_font_size_changed)
        layout.addWidget(_row("Tamano de letra", self.subtitle_font_slider))

        return box

    def _build_colors_group(self) -> QWidget:
        box, layout = _make_collapsible_group("Colores")

        self.band_color_picker = ColorPickerButton(self.config.band_color)
        self.band_color_picker.colorChanged.connect(self._on_band_color_changed)
        layout.addWidget(_row("Banda principal", self.band_color_picker))

        self.accent_color_picker = ColorPickerButton(self.config.accent_color)
        self.accent_color_picker.colorChanged.connect(self._on_accent_color_changed)
        layout.addWidget(_row("Acento (L)", self.accent_color_picker))

        self.text_color_picker = ColorPickerButton(self.config.text_color)
        self.text_color_picker.colorChanged.connect(self._on_text_color_changed)
        layout.addWidget(_row("Texto", self.text_color_picker))

        outline_row = QWidget()
        outline_layout = QHBoxLayout(outline_row)
        outline_layout.setContentsMargins(0, 0, 0, 0)
        self.outline_checkbox = QCheckBox("Contorno del texto")
        self.outline_checkbox.toggled.connect(self._on_outline_enabled_changed)
        self.outline_color_picker = ColorPickerButton(self.config.text_outline_color)
        self.outline_color_picker.colorChanged.connect(self._on_outline_color_changed)
        outline_layout.addWidget(self.outline_checkbox)
        outline_layout.addWidget(self.outline_color_picker, stretch=1)
        layout.addWidget(outline_row)

        restore_btn = QPushButton("Restaurar colores de marca")
        restore_btn.clicked.connect(self._on_restore_brand_colors_clicked)
        layout.addWidget(restore_btn)

        edit_brand_btn = QPushButton("Editar colores de marca...")
        edit_brand_btn.setToolTip("Cambia los colores de marca por defecto (de Portada y de Anotar)")
        edit_brand_btn.clicked.connect(self._on_edit_brand_clicked)
        layout.addWidget(edit_brand_btn)

        swap_btn = QPushButton("Intercambiar banda ↔ acento")
        swap_btn.clicked.connect(self._on_swap_colors_clicked)
        layout.addWidget(swap_btn)

        return box

    def _build_opacity_group(self) -> QWidget:
        box, layout = _make_collapsible_group("Opacidad")

        self.band_opacity_slider = SliderSpinBox(0, 100, round(self.config.band_opacity * 100), suffix="%")
        self.band_opacity_slider.valueChanged.connect(self._on_band_opacity_changed)
        layout.addWidget(_row("Opacidad", self.band_opacity_slider))

        self.accent_opacity_independent_checkbox = QCheckBox("Opacidad independiente para el acento")
        self.accent_opacity_independent_checkbox.toggled.connect(self._on_accent_opacity_independent_toggled)
        layout.addWidget(self.accent_opacity_independent_checkbox)

        self.accent_opacity_slider = SliderSpinBox(0, 100, round(self.config.accent_opacity * 100), suffix="%")
        self.accent_opacity_slider.valueChanged.connect(self._on_accent_opacity_changed)
        self.accent_opacity_row = _row("Opacidad del acento", self.accent_opacity_slider)
        self.accent_opacity_row.setVisible(False)
        layout.addWidget(self.accent_opacity_row)

        return box

    def _build_geometry_group(self) -> QWidget:
        box, layout = _make_collapsible_group("Geometria")

        self.orientation_combo = QComboBox()
        for orientation, label in ORIENTATION_LABELS.items():
            self.orientation_combo.addItem(label, orientation)
        self.orientation_combo.currentIndexChanged.connect(self._on_orientation_changed)
        layout.addWidget(_row("Orientacion de la L", self.orientation_combo))

        self.accent_shift_slider = SliderSpinBox(0, 150, self.config.accent_shift, suffix=" px")
        self.accent_shift_slider.valueChanged.connect(self._on_accent_shift_changed)
        layout.addWidget(_row("Desplazamiento (L)", self.accent_shift_slider))

        self.corner_radius_slider = SliderSpinBox(0, 60, self.config.corner_radius, suffix=" px")
        self.corner_radius_slider.valueChanged.connect(self._on_corner_radius_changed)
        layout.addWidget(_row("Radio de esquina", self.corner_radius_slider))

        self.band_height_slider = SliderSpinBox(50, 500, self.config.band_height, suffix=" px")
        self.band_height_slider.valueChanged.connect(self._on_band_height_changed)
        layout.addWidget(_row("Alto de la banda", self.band_height_slider))

        self.band_margin_left_slider = SliderSpinBox(0, 400, self.config.band_margin_left, suffix=" px")
        self.band_margin_left_slider.valueChanged.connect(self._on_band_margin_left_changed)
        layout.addWidget(_row("Margen izquierdo", self.band_margin_left_slider))

        self.band_margin_top_slider = SliderSpinBox(0, 400, self.config.band_margin_top, suffix=" px")
        self.band_margin_top_slider.valueChanged.connect(self._on_band_margin_top_changed)
        layout.addWidget(_row("Margen superior", self.band_margin_top_slider))

        self.band_width_manual_checkbox = QCheckBox("Ancho manual")
        self.band_width_manual_checkbox.toggled.connect(self._on_band_width_manual_toggled)
        layout.addWidget(self.band_width_manual_checkbox)

        initial_width = self.config.band_width or compute_band_geometry(self.config).width
        self.band_width_slider = SliderSpinBox(100, self.config.canvas.width, initial_width, suffix=" px")
        self.band_width_slider.valueChanged.connect(self._on_band_width_changed)
        self.band_width_row = _row("Ancho de la banda", self.band_width_slider)
        self.band_width_row.setVisible(False)
        layout.addWidget(self.band_width_row)

        self.vertical_position_combo = QComboBox()
        for position, label in VERTICAL_LABELS.items():
            self.vertical_position_combo.addItem(label, position)
        self.vertical_position_combo.currentIndexChanged.connect(self._on_vertical_position_changed)
        layout.addWidget(_row("Posicion vertical", self.vertical_position_combo))

        return box

    def _build_typography_group(self) -> QWidget:
        box, layout = _make_collapsible_group("Tipografia")

        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(self._on_font_family_changed)
        layout.addWidget(_row("Familia", self.font_combo))

        self.font_size_slider = SliderSpinBox(24, 160, self.config.font_size, suffix=" px")
        self.font_size_slider.valueChanged.connect(self._on_font_size_changed)
        layout.addWidget(_row("Tamano", self.font_size_slider))

        self.auto_fit_checkbox = QCheckBox("Ajustar automaticamente")
        self.auto_fit_checkbox.toggled.connect(self._on_auto_fit_toggled)
        layout.addWidget(self.auto_fit_checkbox)

        self.weight_combo = QComboBox()
        self.weight_combo.addItem("Normal", FontWeight.NORMAL)
        self.weight_combo.addItem("Bold", FontWeight.BOLD)
        self.weight_combo.currentIndexChanged.connect(self._on_weight_changed)
        layout.addWidget(_row("Peso", self.weight_combo))

        self.shadow_checkbox = QCheckBox("Sombra del texto")
        self.shadow_checkbox.toggled.connect(self._on_shadow_enabled_toggled)
        layout.addWidget(self.shadow_checkbox)

        self.shadow_intensity_slider = SliderSpinBox(
            0, 100, round(self.config.text_shadow_intensity * 100), suffix="%"
        )
        self.shadow_intensity_slider.valueChanged.connect(self._on_shadow_intensity_changed)
        layout.addWidget(_row("Intensidad de sombra", self.shadow_intensity_slider))

        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1, 4)
        self.max_lines_spin.valueChanged.connect(self._on_max_lines_changed)
        layout.addWidget(_row("Maximo de lineas", self.max_lines_spin))

        return box

    def _build_canvas_group(self) -> QWidget:
        box, layout = _make_collapsible_group("Lienzo")

        self.canvas_combo = QComboBox()
        for label in CANVAS_PRESETS:
            self.canvas_combo.addItem(label)
        self.canvas_combo.currentTextChanged.connect(self._on_canvas_preset_changed)
        layout.addWidget(_row("Tamano de salida", self.canvas_combo))

        self.canvas_width_spin = QSpinBox()
        self.canvas_width_spin.setRange(200, 4000)
        self.canvas_width_spin.setValue(self.config.canvas.width)
        self.canvas_width_spin.valueChanged.connect(self._on_custom_canvas_changed)

        self.canvas_height_spin = QSpinBox()
        self.canvas_height_spin.setRange(200, 4000)
        self.canvas_height_spin.setValue(self.config.canvas.height)
        self.canvas_height_spin.valueChanged.connect(self._on_custom_canvas_changed)

        self.custom_canvas_row = _row("Ancho x alto", self.canvas_width_spin)
        custom_layout = self.custom_canvas_row.layout()
        custom_layout.addWidget(self.canvas_height_spin)
        self.custom_canvas_row.setVisible(False)
        layout.addWidget(self.custom_canvas_row)

        return box

    def _build_output_group(self) -> QWidget:
        box = QGroupBox("Salida")
        layout = QVBoxLayout(box)

        self.save_svg_checkbox = QCheckBox("Guardar tambien el SVG intermedio")
        self.save_svg_checkbox.toggled.connect(self._on_save_svg_toggled)
        layout.addWidget(self.save_svg_checkbox)

        self.fit_warning_label = QLabel("")
        self.fit_warning_label.setStyleSheet("color: #C0392B;")
        self.fit_warning_label.setWordWrap(True)
        self.fit_warning_label.setVisible(False)
        layout.addWidget(self.fit_warning_label)

        generate_btn = QPushButton("Generar")
        generate_btn.setMinimumHeight(44)
        font = generate_btn.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        generate_btn.setFont(font)
        generate_btn.clicked.connect(self._on_generate_clicked)
        layout.addWidget(generate_btn)

        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder_clicked)
        layout.addWidget(self.open_folder_btn)

        return box

    def _build_preview_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Vista previa — arrastra la banda o el subtitulo para reposicionarlos"))

        self.preview_widget = PreviewWidget()
        self.preview_widget.bandRepositioned.connect(self._on_band_dragged)
        self.preview_widget.subtitleRepositioned.connect(self._on_subtitle_dragged)
        self.preview_widget.renderFailed.connect(self._on_preview_render_failed)
        layout.addWidget(self.preview_widget, stretch=1)

        return container

    # ------------------------------------------------------------------
    # Sincronizar config <-> widgets
    # ------------------------------------------------------------------

    def _apply_config_to_widgets(self, config: CoverConfig) -> None:
        """Refleja un CoverConfig completo en todos los controles del panel.

        Los handlers de cada widget mutan self.config al vuelo a medida que
        se van fijando los valores; por eso self.config solo se reemplaza al
        final, con el config recibido. Si se aliaran desde el inicio,
        self.config y config serian el mismo objeto y una mutacion a mitad
        de camino (p. ej. el combo de lienzo) corromperia los valores que
        todavia faltan por aplicar."""
        self.band_color_picker.set_hex_color(config.band_color)
        self.accent_color_picker.set_hex_color(config.accent_color)
        self.text_color_picker.set_hex_color(config.text_color)
        self.outline_color_picker.set_hex_color(config.text_outline_color)
        self.outline_checkbox.setChecked(config.text_outline_enabled)
        self.outline_color_picker.setEnabled(config.text_outline_enabled)

        self.band_opacity_slider.set_value(round(config.band_opacity * 100))
        self.accent_opacity_independent_checkbox.setChecked(config.accent_opacity_independent)
        self.accent_opacity_slider.set_value(round(config.accent_opacity * 100))
        self.accent_opacity_row.setVisible(config.accent_opacity_independent)

        self._select_combo_data(self.orientation_combo, config.orientation)
        self.accent_shift_slider.set_value(config.accent_shift)
        self.corner_radius_slider.set_value(config.corner_radius)
        self.band_height_slider.set_value(config.band_height)
        self.band_margin_left_slider.set_value(config.band_margin_left)
        self.band_margin_top_slider.set_value(config.band_margin_top)
        self.band_width_manual_checkbox.setChecked(config.band_width is not None)
        self.band_width_row.setVisible(config.band_width is not None)
        band_width_value = config.band_width or compute_band_geometry(config).width
        self.band_width_slider.set_value(band_width_value)
        self._select_combo_data(self.vertical_position_combo, config.vertical_position)

        self.font_combo.setCurrentFont(QFont(config.font_family.split(",")[0].strip(" '\"")))
        self.font_size_slider.set_value(config.font_size)
        self.auto_fit_checkbox.setChecked(config.auto_fit_font)
        self._select_combo_data(self.weight_combo, config.font_weight)
        self.shadow_checkbox.setChecked(config.text_shadow_enabled)
        self.shadow_intensity_slider.set_value(round(config.text_shadow_intensity * 100))
        self.max_lines_spin.setValue(config.max_lines)

        matching_label = next(
            (label for label, size in CANVAS_PRESETS.items() if size == config.canvas), "Personalizado"
        )
        self.canvas_combo.setCurrentText(matching_label)
        self.canvas_width_spin.setValue(config.canvas.width)
        self.canvas_height_spin.setValue(config.canvas.height)
        self.custom_canvas_row.setVisible(matching_label == "Personalizado")

        self._select_combo_data(self.subtitle_position_combo, config.subtitle_position)
        self.subtitle_text_color_picker.set_hex_color(config.subtitle_text_color)
        self.subtitle_bg_color_picker.set_hex_color(config.subtitle_bg_color)
        self.subtitle_opacity_slider.set_value(round(config.subtitle_bg_opacity * 100))
        self.subtitle_border_color_picker.set_hex_color(config.subtitle_border_color)
        self.subtitle_border_slider.set_value(config.subtitle_border_width)
        self.subtitle_font_slider.set_value(config.subtitle_font_size)
        self.subtitle_outline_checkbox.setChecked(config.subtitle_outline_enabled)
        self.subtitle_outline_color_picker.set_hex_color(config.subtitle_outline_color)
        self.subtitle_outline_color_picker.setEnabled(config.subtitle_outline_enabled)
        self.subtitle_gradient_checkbox.setChecked(config.subtitle_gradient)
        self.subtitle_gradient_panel.setVisible(config.subtitle_gradient)
        self.subtitle_bg_color2_picker.set_hex_color(config.subtitle_bg_color2)
        self.subtitle_border_gradient_checkbox.setChecked(config.subtitle_border_gradient)
        self.subtitle_border_gradient_panel.setVisible(config.subtitle_border_gradient)
        self.subtitle_border_color2_picker.set_hex_color(config.subtitle_border_color2)
        self._select_combo_data(self.subtitle_gradient_direction_combo, config.subtitle_gradient_direction)
        self.subtitle_gradient_common_panel.setVisible(config.subtitle_gradient or config.subtitle_border_gradient)

        self.save_svg_checkbox.setChecked(config.save_svg_alongside)
        self.config = config
        self._update_subtitle_reset_button()
        self._sync_subtitle_position_spins()

    @staticmethod
    def _select_combo_data(combo: QComboBox, data) -> None:
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Handlers: contenido
    # ------------------------------------------------------------------

    def _on_title_changed(self) -> None:
        self._autofill_output_path()

    def _on_browse_photo_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Elegir foto de fondo", "", "Imagenes (*.png *.jpg *.jpeg *.webp)"
        )
        if path_str:
            self._set_photo(Path(path_str))

    def _set_photo(self, path: Path) -> None:
        if path.suffix.lower() not in SUPPORTED_PHOTO_SUFFIXES:
            QMessageBox.critical(self, "Formato no soportado", f"No se reconoce el formato {path.suffix}.")
            return
        self.photo_path = path
        self.photo_edit.setText(str(path))
        self._autofill_output_path()
        self._schedule_preview_update()

    def _on_output_manually_edited(self, _text: str) -> None:
        self.output_manually_edited = True

    def _autofill_output_path(self) -> None:
        if self.output_manually_edited or self.photo_path is None:
            return
        title_text = self.title_edit.toPlainText().strip()
        slug = _slugify_for_filename(title_text) if title_text else "cover"
        candidate = self.photo_path.parent / f"{slug}-cover.png"
        self.output_edit.setText(str(candidate))

    # ------------------------------------------------------------------
    # Handlers: subtitulo
    # ------------------------------------------------------------------

    def _on_subtitle_position_changed(self, _index: int) -> None:
        self.config.subtitle_position = SubtitlePosition(self.subtitle_position_combo.currentData())
        self.config.subtitle_x = self.config.subtitle_y = None   # elegir una posicion suelta la puesta a mano
        self._update_subtitle_reset_button()

    def _on_subtitle_text_color_changed(self, hex_color: str) -> None:
        self.config.subtitle_text_color = hex_color

    def _on_subtitle_bg_color_changed(self, hex_color: str) -> None:
        self.config.subtitle_bg_color = hex_color

    def _on_subtitle_opacity_changed(self, value: float) -> None:
        self.config.subtitle_bg_opacity = value / 100.0

    def _on_subtitle_border_color_changed(self, hex_color: str) -> None:
        self.config.subtitle_border_color = hex_color

    def _on_subtitle_border_width_changed(self, value: float) -> None:
        self.config.subtitle_border_width = value

    def _on_subtitle_font_size_changed(self, value: float) -> None:
        self.config.subtitle_font_size = value

    def _build_subtitle_layout(self) -> SubtitleLayout | None:
        """Franja del subtitulo con el texto escrito (None si esta vacio), medida con la misma fuente del titulo."""
        return compute_subtitle_layout(self.config, self.subtitle_edit.text(), self._make_measure_fn())

    # ------------------------------------------------------------------
    # Handlers: colores
    # ------------------------------------------------------------------

    def _on_band_color_changed(self, hex_color: str) -> None:
        self.config.band_color = hex_color

    def _on_accent_color_changed(self, hex_color: str) -> None:
        self.config.accent_color = hex_color

    def _on_text_color_changed(self, hex_color: str) -> None:
        self.config.text_color = hex_color

    def _on_outline_enabled_changed(self, checked: bool) -> None:
        self.config.text_outline_enabled = checked
        self.outline_color_picker.setEnabled(checked)

    def _on_outline_color_changed(self, hex_color: str) -> None:
        self.config.text_outline_color = hex_color

    def _on_restore_brand_colors_clicked(self) -> None:
        defaults = default_cover_config()
        self.band_color_picker.set_hex_color(defaults.band_color)
        self.accent_color_picker.set_hex_color(defaults.accent_color)
        self.text_color_picker.set_hex_color(defaults.text_color)
        self.outline_color_picker.set_hex_color(defaults.text_outline_color)
        self.outline_checkbox.setChecked(defaults.text_outline_enabled)
        # los colores del subtitulo (y los segundos colores de sus degradados) tambien son de la marca
        self.subtitle_text_color_picker.set_hex_color(defaults.subtitle_text_color)
        self.subtitle_outline_color_picker.set_hex_color(defaults.subtitle_outline_color)
        self.subtitle_bg_color_picker.set_hex_color(defaults.subtitle_bg_color)
        self.subtitle_bg_color2_picker.set_hex_color(defaults.subtitle_bg_color2)
        self.subtitle_border_color_picker.set_hex_color(defaults.subtitle_border_color)
        self.subtitle_border_color2_picker.set_hex_color(defaults.subtitle_border_color2)

    def _on_edit_brand_clicked(self) -> None:
        dialog = BrandDialog(load_brand(), self)
        if dialog.exec() != BrandDialog.Accepted:
            return
        brand = dialog.brand()
        try:
            path = save_brand(brand)
        except UserSettingsError as exc:
            QMessageBox.critical(self, "No se pudieron guardar los colores de marca", str(exc))
            return
        self.setWindowTitle(f"Cover Studio — {brand.name}")
        if dialog.apply_now():
            self._on_restore_brand_colors_clicked()
            self.annotate_tab.panel.apply_brand_palette()
        self.annotate_tab.panel.refresh_brand()
        suffix = "" if dialog.apply_now() else " Usa 'Restaurar colores de marca' para aplicarlos a lo que tienes abierto."
        self.statusBar().showMessage(f"Colores de marca guardados en {path}.{suffix}")

    def _on_swap_colors_clicked(self) -> None:
        band, accent = self.config.accent_color, self.config.band_color
        self.band_color_picker.set_hex_color(band)
        self.accent_color_picker.set_hex_color(accent)

    # ------------------------------------------------------------------
    # Handlers: opacidad
    # ------------------------------------------------------------------

    def _on_band_opacity_changed(self, value: float) -> None:
        self.config.band_opacity = value / 100.0
        if not self.config.accent_opacity_independent:
            self.config.accent_opacity = self.config.band_opacity

    def _on_accent_opacity_independent_toggled(self, checked: bool) -> None:
        self.config.accent_opacity_independent = checked
        self.accent_opacity_row.setVisible(checked)
        if not checked:
            self.config.accent_opacity = self.config.band_opacity
            self.accent_opacity_slider.set_value(round(self.config.accent_opacity * 100))

    def _on_accent_opacity_changed(self, value: float) -> None:
        self.config.accent_opacity = value / 100.0

    # ------------------------------------------------------------------
    # Handlers: geometria
    # ------------------------------------------------------------------

    def _on_orientation_changed(self, _index: int) -> None:
        self.config.orientation = Orientation(self.orientation_combo.currentData())

    def _on_accent_shift_changed(self, value: float) -> None:
        self.config.accent_shift = value

    def _on_corner_radius_changed(self, value: float) -> None:
        self.config.corner_radius = value

    def _on_band_height_changed(self, value: float) -> None:
        self.config.band_height = value

    def _on_band_margin_left_changed(self, value: float) -> None:
        self.config.band_margin_left = value

    def _on_band_margin_top_changed(self, value: float) -> None:
        self.config.band_margin_top = value

    def _on_band_width_manual_toggled(self, checked: bool) -> None:
        self.band_width_row.setVisible(checked)
        if checked:
            self.config.band_width = self.band_width_slider.value()
        else:
            self.config.band_width = None
            self.band_width_slider.set_value(compute_band_geometry(self.config).width)

    def _on_band_width_changed(self, value: float) -> None:
        if self.band_width_manual_checkbox.isChecked():
            self.config.band_width = value

    def _on_vertical_position_changed(self, _index: int) -> None:
        self.config.vertical_position = VerticalPosition(self.vertical_position_combo.currentData())

    # ------------------------------------------------------------------
    # Handlers: tipografia
    # ------------------------------------------------------------------

    def _on_font_family_changed(self, font: QFont) -> None:
        family = font.family()
        self.config.font_family = f"'{family}', 'Times New Roman', serif"

    def _on_font_size_changed(self, value: float) -> None:
        self.config.font_size = value

    def _on_auto_fit_toggled(self, checked: bool) -> None:
        self.config.auto_fit_font = checked

    def _on_weight_changed(self, _index: int) -> None:
        self.config.font_weight = FontWeight(self.weight_combo.currentData())

    def _on_shadow_enabled_toggled(self, checked: bool) -> None:
        self.config.text_shadow_enabled = checked

    def _on_shadow_intensity_changed(self, value: float) -> None:
        self.config.text_shadow_intensity = value / 100.0

    def _on_max_lines_changed(self, value: int) -> None:
        self.config.max_lines = value

    # ------------------------------------------------------------------
    # Handlers: lienzo
    # ------------------------------------------------------------------

    def _on_canvas_preset_changed(self, label: str) -> None:
        size = CANVAS_PRESETS.get(label)
        is_custom = size is None
        self.custom_canvas_row.setVisible(is_custom)
        if is_custom:
            self.config.canvas = CanvasSize(self.canvas_width_spin.value(), self.canvas_height_spin.value())
        else:
            self.config.canvas = size
            self.canvas_width_spin.blockSignals(True)
            self.canvas_height_spin.blockSignals(True)
            self.canvas_width_spin.setValue(size.width)
            self.canvas_height_spin.setValue(size.height)
            self.canvas_width_spin.blockSignals(False)
            self.canvas_height_spin.blockSignals(False)

    def _on_custom_canvas_changed(self, _value: int) -> None:
        if self.canvas_combo.currentText() == "Personalizado":
            self.config.canvas = CanvasSize(self.canvas_width_spin.value(), self.canvas_height_spin.value())

    # ------------------------------------------------------------------
    # Handlers: salida
    # ------------------------------------------------------------------

    def _on_save_svg_toggled(self, checked: bool) -> None:
        self.config.save_svg_alongside = checked

    def _on_open_folder_clicked(self) -> None:
        if self.last_output_path is not None:
            self._open_folder(self.last_output_path.parent)

    def _open_folder(self, folder: Path) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _refresh_preset_combo(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for path in list_presets(PRESETS_DIR):
            self.preset_combo.addItem(path.stem, path)
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        path = self.preset_combo.itemData(index)
        if not path:
            return
        try:
            config = load_preset(Path(path))
        except PresetError as exc:
            QMessageBox.critical(self, "No se pudo cargar el preset", str(exc))
            return
        self._apply_config_to_widgets(config)
        self.statusBar().showMessage(f"Preset cargado: {Path(path).stem}")

    def _on_save_preset_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "Guardar preset", "Nombre del preset:")
        if not ok or not name.strip():
            return
        try:
            path = save_preset(self.config, name, PRESETS_DIR)
        except PresetError as exc:
            QMessageBox.critical(self, "No se pudo guardar el preset", str(exc))
            return
        self._refresh_preset_combo()
        index = self.preset_combo.findText(path.stem)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self.statusBar().showMessage(f"Preset guardado en {path}")

    def _cover_signature(self) -> tuple:
        """Lo que define la portada de hoy: texto, foto y diseno (una copia, porque el config se muta al vuelo)."""
        return (
            self.title_edit.toPlainText().strip(), self.subtitle_edit.text().strip(), self.photo_path,
            copy.deepcopy(self.config),
        )

    def _has_unsaved_cover(self) -> bool:
        """Hay una portada a medias: tiene contenido y no coincide con la ultima que se genero."""
        has_content = bool(self.title_edit.toPlainText().strip() or self.subtitle_edit.text().strip() or self.photo_path)
        return has_content and self._cover_signature() != self._generated_signature

    def _confirm_discard_cover(self) -> bool:
        answer = QMessageBox.question(
            self, "Nueva portada",
            "La portada actual no se ha generado con estos cambios.\n\nSi empiezas otra se pierde el texto y la foto. "
            "Quieres continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _on_new_cover_clicked(self) -> None:
        if self._has_unsaved_cover() and not self._confirm_discard_cover():
            return
        self.new_cover()

    def new_cover(self) -> None:
        """Empieza otra portada sin cerrar la aplicacion: limpia el contenido (titulo, subtitulo, foto, ruta de salida y
        lo que se mostraba de la anterior) y conserva el diseno."""
        self.title_edit.clear()
        self.subtitle_edit.clear()
        self.photo_path = None
        self.photo_edit.clear()
        self.output_manually_edited = False   # si no, la ruta nueva no se rellenaria sola
        self.output_edit.clear()
        self.last_output_path = None
        self.open_folder_btn.setEnabled(False)
        self.fit_warning_label.setVisible(False)
        self._preview_timer.stop()            # borrar el texto reprogramo la vista previa
        self.preview_widget.clear_preview()
        self._generated_signature = self._cover_signature()
        self.title_edit.setFocus()
        self.statusBar().showMessage("Portada nueva: escribe el titulo y elige una foto.")

    def _on_reset_all_clicked(self) -> None:
        self.output_manually_edited = False
        self._apply_config_to_widgets(default_cover_config())
        self.statusBar().showMessage("Configuracion restablecida a los valores de marca.")

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt override)
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(Path(u.toLocalFile()).suffix.lower() in SUPPORTED_PHOTO_SUFFIXES for u in urls):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt override)
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES:
                if self.tabs.currentWidget() is self.annotate_tab:
                    self.annotate_tab.load_capture(path)
                else:
                    self._set_photo(path)
                break

    # ------------------------------------------------------------------
    # Vista previa en vivo
    # ------------------------------------------------------------------

    def _schedule_preview_update(self, *_args) -> None:
        """Reinicia el debounce de 250 ms; el render real ocurre en
        _trigger_preview_render cuando el usuario deja de tocar controles."""
        self._preview_timer.start()
        if hasattr(self, "subtitle_x_spin"):
            self._sync_subtitle_position_spins()

    def _trigger_preview_render(self) -> None:
        self._sync_subtitle_position_spins()   # los numeros X / Y siguen a la franja (arrastre, texto, tamano...)
        title = self.title_edit.toPlainText().strip()
        if not title:
            return
        title = normalize_title(title)
        band = compute_band_geometry(self.config)
        max_width = max(1.0, band.width - 2 * self.config.inner_margin)
        wrap_result = wrap_title(
            title,
            measure=self._make_measure_fn(),
            max_width=max_width,
            initial_font_size=self.config.font_size,
            max_lines=self.config.max_lines,
            auto_fit=self.config.auto_fit_font,
            min_font_size=24.0,
        )
        self.preview_widget.request_render(
            self.config, wrap_result.lines, wrap_result.font_size, self.photo_path, self._build_subtitle_layout()
        )

    def _on_preview_render_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"No se pudo actualizar la vista previa: {message}")

    def _on_band_dragged(self, new_left: float, new_top: float) -> None:
        """El usuario esta arrastrando la banda en la vista previa. La
        primera vez congela el ancho manual para que no cambie de tamano
        mientras se arrastra (el ancho derivado depende del margen
        izquierdo), y siempre cambia a posicion vertical 'Arriba', que es la
        unica en la que el margen superior es una coordenada literal."""
        if not self.band_width_manual_checkbox.isChecked():
            self.band_width_manual_checkbox.setChecked(True)

        band = compute_band_geometry(self.config)
        max_left = max(0.0, self.config.canvas.width - band.width)
        max_top = max(0.0, self.config.canvas.height - band.height)
        clamped_left = min(max(0.0, new_left), max_left)
        clamped_top = min(max(0.0, new_top), max_top)

        if self.config.vertical_position is not VerticalPosition.TOP:
            self._select_combo_data(self.vertical_position_combo, VerticalPosition.TOP)

        self.band_margin_left_slider.set_value(clamped_left)
        self.band_margin_top_slider.set_value(clamped_top)
        self.config.band_margin_left = clamped_left
        self.config.band_margin_top = clamped_top
        # set_value no emite senales: sin esto la vista previa se quedaba en la primera posicion del arrastre
        self._trigger_preview_render()

    def _on_subtitle_dragged(self, new_left: float, new_top: float) -> None:
        """El usuario arrastra el subtitulo en la vista previa: su esquina superior izquierda queda en
        `subtitle_x/y` (dentro del lienzo) y deja de seguir a la posicion del combo."""
        layout = self._build_subtitle_layout()
        if layout is None:
            return
        canvas, rect = self.config.canvas, layout.rect
        # a pixeles enteros: un borde de 2 px que cae entre dos pixeles sale difuso
        self.config.subtitle_x = float(min(max(0, round(new_left)), max(0, canvas.width - rect.width)))
        self.config.subtitle_y = float(min(max(0, round(new_top)), max(0, canvas.height - rect.height)))
        self._update_subtitle_reset_button()
        self._trigger_preview_render()

    # --- degradado y contorno del texto -------------------------------------------------------

    def _on_subtitle_gradient_toggled(self, checked: bool) -> None:
        self.config.subtitle_gradient = checked
        self.subtitle_gradient_panel.setVisible(checked)
        self._update_subtitle_gradient_common_visibility()

    def _on_subtitle_border_gradient_toggled(self, checked: bool) -> None:
        self.config.subtitle_border_gradient = checked
        self.subtitle_border_gradient_panel.setVisible(checked)
        self._update_subtitle_gradient_common_visibility()

    def _on_subtitle_border_color2_changed(self, hex_color: str) -> None:
        self.config.subtitle_border_color2 = hex_color

    def _update_subtitle_gradient_common_visibility(self) -> None:
        """La direccion y el boton de colores de marca sirven a los dos degradados: se ven si alguno esta activo."""
        self.subtitle_gradient_common_panel.setVisible(
            self.subtitle_gradient_checkbox.isChecked() or self.subtitle_border_gradient_checkbox.isChecked()
        )

    def _on_subtitle_bg_color2_changed(self, hex_color: str) -> None:
        self.config.subtitle_bg_color2 = hex_color

    def _on_subtitle_gradient_direction_changed(self, _index: int) -> None:
        self.config.subtitle_gradient_direction = GradientDirection(self.subtitle_gradient_direction_combo.currentData())

    def _on_subtitle_brand_gradient_clicked(self) -> None:
        """Los colores de la identidad de la portada. Relleno: del verde de la banda al azul del acento. Borde: del
        azul al verde (al reves, para que el borde se distinga del relleno). Se aplica a los degradados que estan
        encendidos; si no hay ninguno, enciende los dos."""
        fill_on = self.subtitle_gradient_checkbox.isChecked()
        border_on = self.subtitle_border_gradient_checkbox.isChecked()
        if not fill_on and not border_on:
            fill_on = border_on = True
        if fill_on:
            self.subtitle_gradient_checkbox.setChecked(True)
            self.subtitle_bg_color_picker.set_hex_color(self.config.band_color)
            self.subtitle_bg_color2_picker.set_hex_color(self.config.accent_color)
        if border_on:
            self.subtitle_border_gradient_checkbox.setChecked(True)
            self.subtitle_border_color_picker.set_hex_color(self.config.accent_color)
            self.subtitle_border_color2_picker.set_hex_color(self.config.band_color)

    def _on_subtitle_outline_toggled(self, checked: bool) -> None:
        self.config.subtitle_outline_enabled = checked
        self.subtitle_outline_color_picker.setEnabled(checked)

    def _on_subtitle_outline_color_changed(self, hex_color: str) -> None:
        self.config.subtitle_outline_color = hex_color

    # --- coordenadas exactas y empujes ----------------------------------------------------------

    def _sync_subtitle_position_spins(self) -> None:
        """Muestra en X / Y donde esta ahora la franja (sea automatica, arrastrada o escrita) y ajusta los
        limites para que no se pueda sacar del lienzo. Sin texto de subtitulo no hay franja: se apagan."""
        layout = self._build_subtitle_layout()
        has_layout = layout is not None
        for widget in (self.subtitle_x_spin, self.subtitle_y_spin, *self.subtitle_nudge_buttons.values()):
            widget.setEnabled(has_layout)
        if layout is None:
            return
        canvas, rect = self.config.canvas, layout.rect
        self._syncing_subtitle_position = True
        try:
            self.subtitle_x_spin.setRange(0, max(0, int(canvas.width - rect.width)))
            self.subtitle_y_spin.setRange(0, max(0, int(canvas.height - rect.height)))
            self.subtitle_x_spin.setValue(round(rect.x))
            self.subtitle_y_spin.setValue(round(rect.y))
        finally:
            self._syncing_subtitle_position = False

    def _on_subtitle_coordinate_edited(self, _value: int) -> None:
        """El usuario escribio X o Y: la franja queda en esas coordenadas (el otro eje, donde ya estaba)."""
        if self._syncing_subtitle_position:
            return
        self.config.subtitle_x = float(self.subtitle_x_spin.value())
        self.config.subtitle_y = float(self.subtitle_y_spin.value())
        self._update_subtitle_reset_button()
        self._trigger_preview_render()

    def _nudge_subtitle(self, dx: int, dy: int) -> None:
        """Mueve la franja `dx`, `dy` pasos de N px desde donde esta (en diagonal si se combinan)."""
        layout = self._build_subtitle_layout()
        if layout is None:
            return
        step = self.subtitle_step_spin.value()
        self._on_subtitle_dragged(round(layout.rect.x) + dx * step, round(layout.rect.y) + dy * step)

    def _on_subtitle_reset_position_clicked(self) -> None:
        self.config.subtitle_x = self.config.subtitle_y = None
        self._update_subtitle_reset_button()
        self._sync_subtitle_position_spins()
        self._schedule_preview_update()

    def _update_subtitle_reset_button(self) -> None:
        self.subtitle_reset_position_btn.setEnabled(self.config.subtitle_x is not None)

    # ------------------------------------------------------------------
    # Medicion de texto y generacion
    # ------------------------------------------------------------------

    def _make_measure_fn(self):
        family = self.config.font_family.split(",")[0].strip(" '\"")
        is_bold = self.config.font_weight is FontWeight.BOLD

        def measure(text: str, size: float) -> float:
            font = QFont(family)
            font.setPixelSize(max(1, round(size)))
            font.setBold(is_bold)
            return QFontMetricsF(font).horizontalAdvance(text)

        return measure

    def _on_generate_clicked(self) -> None:
        raw_title = self.title_edit.toPlainText().strip()
        if not raw_title:
            QMessageBox.critical(self, "Falta el titulo", "Escribe un titulo antes de generar la portada.")
            return

        output_text = self.output_edit.text().strip()
        if not output_text:
            QMessageBox.critical(self, "Falta la ruta de salida", "Indica donde guardar la portada.")
            return
        output_path = Path(output_text)

        if self.photo_path is not None and output_path.resolve() == self.photo_path.resolve():
            if not self._confirm_overwrite(output_path):
                return

        title = normalize_title(raw_title)
        band = compute_band_geometry(self.config)
        max_width = max(1.0, band.width - 2 * self.config.inner_margin)
        wrap_result = wrap_title(
            title,
            measure=self._make_measure_fn(),
            max_width=max_width,
            initial_font_size=self.config.font_size,
            max_lines=self.config.max_lines,
            auto_fit=self.config.auto_fit_font,
            min_font_size=24.0,
        )

        self.fit_warning_label.setVisible(not wrap_result.fits)
        if not wrap_result.fits:
            self.fit_warning_label.setText(
                "El titulo no cabe en la banda con el tamano y numero de lineas actuales. "
                "Se genero igual, pero revisa la portada."
            )

        try:
            svg_text = build_svg(
                self.config,
                lines=wrap_result.lines,
                font_size=wrap_result.font_size,
                photo_path=self.photo_path,
                subtitle=self._build_subtitle_layout(),
            )
        except GeometryError as exc:
            QMessageBox.critical(self, "No se pudo generar la portada", str(exc))
            return

        start = time.perf_counter()
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            render_png(svg_text, output_path, self.config.canvas.width, self.config.canvas.height)
        except GeometryError as exc:
            QMessageBox.critical(self, "No se pudo guardar el PNG", str(exc))
            return
        except OSError as exc:
            QMessageBox.critical(self, "Ruta de salida no escribible", str(exc))
            return
        elapsed = time.perf_counter() - start

        if self.config.save_svg_alongside:
            output_path.with_suffix(".svg").write_text(svg_text, encoding="utf-8")

        self.last_output_path = output_path
        self._generated_signature = self._cover_signature()
        self.open_folder_btn.setEnabled(True)
        self.statusBar().showMessage(f"Guardado en {output_path} · {elapsed:.2f}s")
        self._trigger_preview_render()

    def _confirm_overwrite(self, output_path: Path) -> bool:
        dialog = OverwriteConfirmDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return False

        backup_path = output_path.with_name(f"{output_path.stem}.original{output_path.suffix}")
        try:
            shutil.copy2(output_path, backup_path)
        except OSError as exc:
            QMessageBox.critical(self, "No se pudo respaldar la foto original", str(exc))
            return False

        self.statusBar().showMessage(f"Copia de la foto original guardada en {backup_path}")
        return True
