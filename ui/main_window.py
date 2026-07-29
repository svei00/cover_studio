"""Ventana principal de Cover Studio."""

from __future__ import annotations

import re
import shutil
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QFontMetricsF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QStyle,
    QVBoxLayout,
    QWidget,
)

from core.geometry import (
    CanvasSize,
    CoverConfig,
    FontWeight,
    GeometryError,
    Orientation,
    VerticalPosition,
    build_svg,
    compute_band_geometry,
    render_png,
)
from core.presets import PresetError, list_presets, load_preset, save_preset
from core.text_utils import normalize_title, wrap_title
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


class OverwriteConfirmDialog(QDialog):
    """Exige escribir SOBRESCRIBIR para habilitar el boton de confirmar,
    con friccion real antes de perder la foto original sin banner."""

    CONFIRM_WORD = "SOBRESCRIBIR"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirmar sobrescritura")

        icon_label = QLabel()
        style = self.style()
        if style is not None:
            icon_label.setPixmap(style.standardIcon(QStyle.SP_MessageBoxWarning).pixmap(32, 32))

        message = QLabel(
            "Vas a sobrescribir la imagen original. Esta accion no se puede "
            "deshacer y perderas la foto limpia sin banner."
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


class MainWindow(QMainWindow):
    """Ventana principal: entradas, panel de diseno, vista previa y generacion."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cover Studio — Excel Solutions")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self.config = CoverConfig()
        self.photo_path: Path | None = None
        self.output_manually_edited = False
        self.last_output_path: Path | None = None

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
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        root_layout.addLayout(self._build_preset_bar())

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_preview_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._connect_preview_triggers()
        self.statusBar().showMessage("Listo.")

    def _connect_preview_triggers(self) -> None:
        """Cualquier control que cambie el diseno o el contenido debe
        reprogramar la vista previa en vivo (con debounce)."""
        triggers = [
            self.title_edit.textChanged,
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
        scroll.setMinimumWidth(420)
        scroll.setMaximumWidth(480)

        container = QWidget()
        layout = QVBoxLayout(container)

        layout.addWidget(self._build_input_group())
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
        layout.addWidget(QLabel("Vista previa — arrastra la banda para reposicionarla"))

        self.preview_widget = PreviewWidget()
        self.preview_widget.bandRepositioned.connect(self._on_band_dragged)
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

        self.save_svg_checkbox.setChecked(config.save_svg_alongside)
        self.config = config

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
        defaults = CoverConfig()
        self.band_color_picker.set_hex_color(defaults.band_color)
        self.accent_color_picker.set_hex_color(defaults.accent_color)
        self.text_color_picker.set_hex_color(defaults.text_color)
        self.outline_color_picker.set_hex_color(defaults.text_outline_color)
        self.outline_checkbox.setChecked(defaults.text_outline_enabled)

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

    def _on_reset_all_clicked(self) -> None:
        self.output_manually_edited = False
        self._apply_config_to_widgets(CoverConfig())
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
                self._set_photo(path)
                break

    # ------------------------------------------------------------------
    # Vista previa en vivo
    # ------------------------------------------------------------------

    def _schedule_preview_update(self, *_args) -> None:
        """Reinicia el debounce de 250 ms; el render real ocurre en
        _trigger_preview_render cuando el usuario deja de tocar controles."""
        self._preview_timer.start()

    def _trigger_preview_render(self) -> None:
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
        self.preview_widget.request_render(self.config, wrap_result.lines, wrap_result.font_size, self.photo_path)

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
