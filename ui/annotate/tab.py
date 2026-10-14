"""Pestana "Anotar": abre o pega una captura, permite anotarla con el mouse
(marcador, flecha, paso, texto, pixelado) con deshacer/rehacer, y la exporta."""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.annotate.bounds import required_padding
from core.brand import brand_palette
from core.annotate.errors import AnnotateError
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import AnnotationDoc, IconKind, ImageOverlay, Magnifier, Redaction
from core.annotate.primitives import build_primitives
from core.annotate.raster import (
    active_spotlight,
    apply_overlays,
    apply_redactions,
    apply_spotlight,
    lens_crops,
    load_image,
    missing_overlays,
)
from core.annotate.upscale import FACTORS, save_upscaled, scaled_output_path
from core.annotate.svg import default_output_path, export_png, export_svg, render_bytes
from core.geometry import SUPPORTED_PHOTO_SUFFIXES, GeometryError
from ui.annotate.canvas import ZOOM_BUTTON_STEP, AnnotateCanvas
from ui.annotate.controller import STICKY_TOOLS, EditController, Tool
from ui.annotate.icon_pixmap import ICON_LABELS, icon_for
from ui.annotate.panel import PropertiesPanel
from ui.dialogs import OverwriteConfirmDialog
from ui.flow_layout import FlowLayout, spacer


def captures_dir() -> Path:
    """Carpeta donde se guardan las capturas pegadas desde el portapapeles."""
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return Path(pictures or Path.home()) / "Cover Studio"


def pil_to_qimage(img: Image.Image) -> QImage:
    rgba = img.convert("RGBA")
    qimage = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888)
    return qimage.copy()  # desacopla el QImage del buffer temporal de Python


TOOL_BUTTONS = (
    (Tool.SELECT, "Seleccionar", "Selecciona, mueve y redimensiona anotaciones"),
    (Tool.MARKER, "Marcador", "Recuadro con resplandor dorado y flecha: arrastra sobre la captura"),
    (Tool.MARKER_PLAIN, "Recuadro", "Marcador sin flecha: el mismo recuadro con resplandor, sin la flecha"),
    (Tool.HIGHLIGHT, "Resaltar", "Resaltador: pinta una zona (texto, celdas) con un color translucido; arrastra sobre ella"),
    (Tool.ARROW, "Flecha", "Flecha suelta: arrastra del inicio a la punta"),
    (Tool.LINE, "Linea", "Linea recta (sirve de conector): arrastra del inicio al final; las puntas y el estilo se eligen en el panel"),
    (Tool.PEN, "Lapiz", "Dibuja a mano alzada: mantén el boton y arrastra. El trazo se suaviza solo al soltar"),
    (Tool.PEN_MARKER, "Resaltador libre", "Resalta a mano alzada con un trazo ancho que deja ver (y leer) lo de abajo"),
    (Tool.STEP, "Paso", "Circulo numerado: clic donde va; la numeracion continua sola"),
    (Tool.CHECK, "Check", "Icono de check (verde por defecto): clic donde va; el color y el estilo se cambian en el panel"),
    (Tool.CROSS, "Cruz", "Icono de cruz (rojo por defecto): clic donde va; el color y el estilo se cambian en el panel"),
    (Tool.ICON, "Icono", "Otros iconos (alerta, info, pregunta, estrella, mas, menos): elige uno en la flecha y haz clic donde va"),
    (Tool.TEXT, "Texto", "Etiqueta de texto: clic donde va y escribe en el panel"),
    (Tool.REDACT, "Pixelar", "Pixela una zona para anonimizar (RFC, nombres, UUID)"),
    (Tool.FOCUS, "Foco", "Oscurece o desenfoca todo menos una zona (solo un foco por captura). El desenfoque NO oculta datos: usa Pixelar"),
    (Tool.LENS, "Lupa", "Amplia una zona en un lente aparte: arrastra sobre lo que quieres ampliar"),
    (Tool.CROP, "Recortar", "Recorta la captura: arrastra lo que se queda; se puede deshacer y no toca el original"),
)


class AnnotateTab(QWidget):
    statusMessage = Signal(str)
    dirtyChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc: AnnotationDoc | None = None
        self.base_image: Image.Image | None = None

        self.open_btn = QPushButton("Abrir...")
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.paste_btn = QPushButton("Pegar (CTRL + V)")
        self.paste_btn.clicked.connect(self.paste_capture)
        self.save_btn = QPushButton("Guardar proyecto")
        self.save_btn.setToolTip("CTRL + S: guarda las anotaciones junto a la captura para poder reabrirlas")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_project)
        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.setToolTip("CTRL + C: copia la captura anotada al portapapeles")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.export_btn = QPushButton("Exportar PNG...")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.scale_btn = QPushButton("Escalar")
        self.scale_btn.setToolTip(
            "Agranda la captura ORIGINAL (sin anotaciones) con remuestreo Lanczos y un poco de nitidez y la guarda "
            "como nombre@2x.png. No inventa detalle: sirve para que el texto se vea suave al ampliar. "
            "Abre el resultado con Abrir... para anotarlo."
        )
        self.scale_btn.setEnabled(False)
        scale_menu = QMenu(self.scale_btn)
        self.scale_actions = {}
        for factor in FACTORS:
            action = scale_menu.addAction(f"Escalar a {factor}x...")
            action.triggered.connect(lambda _checked=False, f=factor: self._on_scale_clicked(f))
            self.scale_actions[factor] = action
        scale_menu.addSeparator()
        self.sharpen_action = scale_menu.addAction("Con nitidez")
        self.sharpen_action.setCheckable(True)
        self.sharpen_action.setChecked(True)
        self.scale_btn.setMenu(scale_menu)
        self.svg_checkbox = QCheckBox("Guardar tambien el SVG")
        self.info_label = QLabel("Sin captura.")
        # la etiqueta cede espacio (se recorta) antes de ensanchar la ventana: la barra de arriba ya va justa
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        bar = QHBoxLayout()
        bar.addWidget(self.open_btn)
        bar.addWidget(self.paste_btn)
        bar.addWidget(self.info_label, stretch=1)
        bar.addWidget(self.svg_checkbox)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.export_btn)
        bar.addWidget(self.scale_btn)

        self.controller = EditController(self)
        self.canvas = AnnotateCanvas()
        self.canvas.set_controller(self.controller)
        self.panel = PropertiesPanel(self.controller)
        self._base_key: tuple | None = None
        self._base_qimage: QImage | None = None
        self._redacted: Image.Image | None = None
        self._spot_key: object = None
        self._warned_missing: set[str] = set()   # imagenes pegadas cuyo archivo falta y ya se aviso
        self._lens_cache: dict[str, tuple[tuple, QImage]] = {}

        tools = FlowLayout()   # si no caben en una fila, bajan a la siguiente (la ventana no se ensancha)
        self.tool_buttons: dict[Tool, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for tool, label, tip in TOOL_BUTTONS:
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip + (" (sigue activa tras dibujar; Esc para salir)" if tool in STICKY_TOOLS else ""))
            button.setCheckable(True)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked, t=tool: self.controller.set_tool(t))
            group.addButton(button)
            self.tool_buttons[tool] = button
            tools.addWidget(button)
        self.tool_buttons[Tool.SELECT].setChecked(True)
        self.paste_over_btn = QToolButton()
        self.paste_over_btn.setText("Pegar encima")
        self.paste_over_btn.setToolTip(
            "CTRL + MAYUS + V: pega la imagen del portapapeles ENCIMA de la captura (a su tamano real) para moverla y "
            "redimensionarla; CTRL + V sigue reemplazando la captura"
        )
        self.paste_over_btn.setEnabled(False)
        self.paste_over_btn.clicked.connect(self.paste_overlay)
        tools.addWidget(self.paste_over_btn)
        self._build_icon_buttons()
        self.controller.iconDefaultsChanged.connect(self._refresh_icon_button)
        tools.addWidget(spacer(16))
        self.undo_btn = QToolButton()
        self.undo_btn.setText("Deshacer")
        self.undo_btn.setToolTip("CTRL + Z")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.controller.undo)
        self.redo_btn = QToolButton()
        self.redo_btn.setText("Rehacer")
        self.redo_btn.setToolTip("CTRL + Y")
        self.redo_btn.setEnabled(False)
        self.redo_btn.clicked.connect(self.controller.redo)
        self.delete_btn = QToolButton()
        self.delete_btn.setText("Borrar")
        self.delete_btn.setToolTip("Suprimir, con la captura enfocada")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.controller.delete_selected)
        for widget in (self.undo_btn, self.redo_btn, self.delete_btn):
            tools.addWidget(widget)

        self.fit_btn = QToolButton()
        self.fit_btn.setText("Ajustar")
        self.fit_btn.setToolTip("Ajusta la captura a la ventana (CTRL + 0)")
        self.fit_btn.clicked.connect(self.canvas.fit)
        self.actual_btn = QToolButton()
        self.actual_btn.setText("100 %")
        self.actual_btn.setToolTip("Un pixel de la captura por pixel de pantalla (CTRL + 1)")
        self.actual_btn.clicked.connect(self.canvas.actual_size)
        self.zoom_label = QLabel("Zoom: -")
        zoom_hint = QLabel("Rueda: zoom - Boton central o Espacio + arrastrar: mover")
        zoom_hint.setStyleSheet("color: #888888;")
        zoom_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # en ventanas estrechas se recorta
        zoom_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        zoom_row = QHBoxLayout()
        for widget in (self.fit_btn, self.actual_btn, self.zoom_label):
            zoom_row.addWidget(widget)
        zoom_row.addStretch(1)
        zoom_row.addWidget(zoom_hint)
        self.canvas.zoomChanged.connect(self._on_zoom_changed)

        canvas_column = QVBoxLayout()
        canvas_column.addWidget(self.canvas, stretch=1)
        canvas_column.addLayout(zoom_row)
        body = QHBoxLayout()
        body.addLayout(canvas_column, stretch=1)
        body.addWidget(self.panel)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addLayout(tools)
        layout.addLayout(body, stretch=1)

        self.controller.changed.connect(self.refresh)
        self.controller.toolChanged.connect(self._on_tool_changed)
        self.controller.selectionChanged.connect(self._update_history_buttons)
        self.controller.stack.canUndoChanged.connect(self._update_history_buttons)
        self.controller.stack.canRedoChanged.connect(self._update_history_buttons)
        self.controller.stack.cleanChanged.connect(self._on_clean_changed)

        for key, slot in ((QKeySequence.StandardKey.Paste, self.paste_capture),
                          (QKeySequence("Ctrl+Shift+V"), self.paste_overlay),
                          (QKeySequence.StandardKey.Undo, self.controller.undo),
                          (QKeySequence.StandardKey.Redo, self.controller.redo),
                          (QKeySequence.StandardKey.Save, self.save_project),
                          (QKeySequence.StandardKey.Copy, self.copy_to_clipboard),
                          (QKeySequence.StandardKey.SelectAll, self.controller.select_all),
                          (QKeySequence("Ctrl+0"), self.canvas.fit),
                          (QKeySequence("Ctrl+1"), self.canvas.actual_size),
                          (QKeySequence.StandardKey.ZoomIn, lambda: self.canvas.zoom_at(ZOOM_BUTTON_STEP)),
                          (QKeySequence.StandardKey.ZoomOut, lambda: self.canvas.zoom_at(1 / ZOOM_BUTTON_STEP))):
            shortcut = QShortcut(QKeySequence(key), self)
            # de la ventana, no solo de lo que esta dentro de la pestana: al cambiar de pestana con el mouse el foco se queda en
            # la barra de pestanas (fuera de este widget) y con WidgetWithChildren Ctrl+V / Ctrl+C no hacian nada. Qt solo
            # activa el atajo mientras la pestana esta visible, asi que no choca con los de la pestana Portada, y los
            # cuadros de texto (que aceptan Copiar, Pegar y Deshacer por su cuenta) siguen mandando en lo suyo.
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(slot)

    def _on_zoom_changed(self, scale: float) -> None:
        mode = " (ajustado)" if self.canvas.is_fitted() else ""
        self.zoom_label.setText(f"Zoom: {scale * 100:.0f} %{mode}")

    def _on_clean_changed(self, clean: bool) -> None:
        self.dirtyChanged.emit(not clean)

    def _build_icon_buttons(self) -> None:
        """Check y Cruz con su miniatura; Icono con un menu para elegir cual de los otros se coloca."""
        for tool, kind in ((Tool.CHECK, IconKind.CHECK), (Tool.CROSS, IconKind.CROSS)):
            self._decorate_icon_button(self.tool_buttons[tool], kind)
        button = self.tool_buttons[Tool.ICON]
        self._decorate_icon_button(button, self.controller.icon_kind)
        button.setPopupMode(QToolButton.MenuButtonPopup)
        menu = QMenu(button)
        self.icon_actions: dict[IconKind, QAction] = {}
        for kind, label in ICON_LABELS.items():
            if kind in (IconKind.CHECK, IconKind.CROSS):
                continue   # estos dos ya tienen su boton
            action = menu.addAction(icon_for(kind), label)
            action.triggered.connect(lambda _checked=False, k=kind: self._choose_icon(k))
            self.icon_actions[kind] = action
        button.setMenu(menu)

    @staticmethod
    def _decorate_icon_button(button: QToolButton, kind: IconKind) -> None:
        button.setIcon(icon_for(kind, px=16))
        button.setIconSize(QSize(14, 14))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

    def _refresh_icon_button(self) -> None:
        self._decorate_icon_button(self.tool_buttons[Tool.ICON], self.controller.icon_kind)

    def _choose_icon(self, kind: IconKind) -> None:
        """Elegir uno en el menu de Icono: ese es el que se coloca y la herramienta queda activa."""
        self.controller.set_icon_defaults(kind=kind)
        self.controller.set_tool(Tool.ICON)
        self.tool_buttons[Tool.ICON].setChecked(True)

    def _on_tool_changed(self, tool: Tool) -> None:
        self.tool_buttons[tool].setChecked(True)

    def _update_history_buttons(self) -> None:
        stack = self.controller.stack
        self.undo_btn.setEnabled(stack.canUndo())
        self.redo_btn.setEnabled(stack.canRedo())
        self.delete_btn.setEnabled(bool(self.controller.selected_ids))

    # ------------------------------------------------------------------
    # Cargar
    # ------------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir captura o proyecto",
            "",
            "Capturas y proyectos (*.png *.jpg *.jpeg *.webp *.anotar.json)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.name.endswith(".anotar.json"):
            self.open_project(path)
        else:
            self.load_capture(path)

    def open_project(self, project: Path) -> None:
        """Abre un proyecto de anotaciones (.anotar.json) y la captura a la que apunta."""
        try:
            doc = load_doc(project)
        except GeometryError as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", str(exc))
            return
        self.load_capture(doc.image_path, project=project)

    # ------------------------------------------------------------------
    # Cambios sin guardar
    # ------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return self.doc is not None and not self.controller.stack.isClean()

    def _ask_discard(self) -> str:
        """Pregunta que hacer con los cambios sin guardar: 'save', 'discard' o 'cancel'."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Cambios sin guardar")
        box.setText("Hay anotaciones sin guardar en la captura actual.")
        save = box.addButton("Guardar proyecto", QMessageBox.AcceptRole)
        discard = box.addButton("Descartar", QMessageBox.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        return "discard" if clicked is discard else "cancel"

    def confirm_discard(self) -> bool:
        """True si se puede seguir (no hay cambios, se guardaron o se descartan)."""
        if not self.is_dirty():
            return True
        choice = self._ask_discard()
        if choice == "save":
            return self.save_project()
        return choice == "discard"

    def save_project(self) -> bool:
        """Guarda las anotaciones junto a la captura (captura.anotar.json)."""
        if self.doc is None:
            return False
        try:
            path = save_doc(self.doc)
        except GeometryError as exc:
            QMessageBox.critical(self, "No se pudo guardar el proyecto", str(exc))
            return False
        self.controller.stack.setClean()
        self.statusMessage.emit(f"Proyecto guardado en {path}")
        return True

    def copy_to_clipboard(self) -> None:
        """Copia la captura anotada (con su margen) al portapapeles como imagen."""
        if self.doc is None:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = render_bytes(self.doc)
        except GeometryError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo copiar", str(exc))
            return
        QApplication.restoreOverrideCursor()
        image = QImage.fromData(data, "PNG")
        QGuiApplication.clipboard().setImage(image)
        self.statusMessage.emit(f"Copiada al portapapeles ({image.width()} x {image.height()} px)")

    def _clipboard_source(self, prefix: str, what: str) -> tuple[Path | None, str]:
        """La imagen del portapapeles como archivo: (ruta, 'file') si se copio un archivo de imagen (se usa tal cual),
        (ruta, 'saved') si era una imagen y se guardo en Imagenes/Cover Studio con un nombre nuevo, (None, 'none') si no hay
        imagen o (None, 'error') si no se pudo guardar (ya se aviso con un cuadro)."""
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES:
                    return path, "file"
        if mime is not None and mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                folder = captures_dir()
                stamp = f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    QMessageBox.critical(self, f"No se pudo guardar {what}", str(exc))
                    return None, "error"
                path = folder / f"{stamp}.png"
                n = 2
                while path.exists():   # dos pegados en el mismo segundo no se pisan (el proyecto referencia el archivo)
                    path = folder / f"{stamp}-{n}.png"
                    n += 1
                if not image.save(str(path), "PNG"):
                    QMessageBox.critical(self, f"No se pudo guardar {what}", str(path))
                    return None, "error"
                return path, "saved"
        return None, "none"

    def paste_capture(self) -> None:
        """Pega la imagen del portapapeles (se guarda en Imagenes/Cover Studio)
        o, si se copio un archivo de imagen, lo abre."""
        path, how = self._clipboard_source("captura", "la captura pegada")
        if path is not None:
            self.load_capture(path)
            if how == "saved":
                self.statusMessage.emit(f"Captura pegada y guardada en {path}")
        elif how == "none":
            self.statusMessage.emit("No hay una imagen en el portapapeles.")

    def paste_overlay(self) -> None:
        """CTRL + MAYUS + V: pega la imagen del portapapeles ENCIMA de la captura abierta (a su tamano real, centrada) como
        un elemento que se mueve y se redimensiona. La captura no se reemplaza."""
        if self.doc is None or self.base_image is None:
            self.statusMessage.emit("Abre primero una captura: la imagen se pega encima de ella (CTRL + V la abre).")
            return
        path, how = self._clipboard_source("pegada", "la imagen pegada")
        if path is None:
            if how == "none":
                self.statusMessage.emit("No hay una imagen en el portapapeles.")
            return
        try:
            size = load_image(path).size
        except AnnotateError as exc:
            QMessageBox.critical(self, "No se pudo pegar la imagen", str(exc))
            return
        self.controller.add_overlay(path, size)
        self.statusMessage.emit(
            f"Imagen pegada encima ({size[0]} x {size[1]} px). Arrastrala para moverla; las esquinas la redimensionan "
            f"sin deformarla (Mayus mientras arrastras: libre)."
        )

    def load_capture(self, path: Path, project: Path | None = None) -> None:
        """Abre una captura; si junto a ella hay un proyecto de anotaciones
        (.anotar.json) del mismo tamano, lo recupera. `project` fuerza cual usar."""
        if not self.confirm_discard():
            return
        try:
            image = load_image(path)
        except AnnotateError as exc:
            QMessageBox.critical(self, "No se pudo abrir la captura", str(exc))
            return

        doc = AnnotationDoc(path, image.size, palette=brand_palette())   # un documento nuevo parte de la marca
        note = ""
        sidecar = project or sidecar_path(path)
        if sidecar.exists():
            try:
                saved = load_doc(sidecar)
                if tuple(saved.image_size) == image.size:
                    doc = AnnotationDoc(path, image.size, saved.items, saved.style_scale, saved.padding, saved.palette, saved.crop)
                    note = f" ({len(doc.items)} anotaciones recuperadas)"
                else:
                    note = " (el proyecto guardado era de otra imagen; se ignoro)"
            except AnnotateError as exc:
                note = f" (no se pudo leer el proyecto guardado: {exc})"

        self.base_image = image
        self.doc = doc
        self._base_key = None
        self._spot_key = None
        self.canvas.reset_view()   # otra captura: se empieza ajustada
        self.export_btn.setEnabled(True)
        for button in self.tool_buttons.values():
            button.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self.scale_btn.setEnabled(True)
        self.paste_over_btn.setEnabled(True)
        self.controller.set_doc(doc)
        self.statusMessage.emit(f"Captura abierta: {path}{note}")

    def refresh(self) -> None:
        """Vuelve a pintar la captura con el pixelado y las anotaciones actuales."""
        if self.doc is None or self.base_image is None:
            self.canvas.set_content(None, [])
            self.info_label.setText("Sin captura.")
            return
        # el bitmap pixelado solo se recalcula si cambiaron las imagenes pegadas (o la escala de su sombra) o los pixelados
        overlays = tuple(i for i in self.doc.items if isinstance(i, ImageOverlay))
        key = (overlays, round(self.controller.scale(), 4) if overlays else None,
               tuple(i for i in self.doc.items if isinstance(i, Redaction)))
        spot_key = active_spotlight(self.doc.items)
        if key != self._base_key or self._base_qimage is None or self._redacted is None:
            composed = apply_overlays(self.base_image, self.doc.items, self.controller.scale())
            self._redacted = apply_redactions(composed, self.doc.items)
            self._warn_missing_overlays(overlays)
            self._base_key = key
            self._spot_key = object()   # el foco se aplica sobre el bitmap pixelado: hay que rehacerlo
            self._lens_cache.clear()
        if spot_key != self._spot_key or self._base_qimage is None:
            # el foco solo afecta al fondo: las lupas se siguen recortando de la imagen pixelada, sin foco
            self._base_qimage = pil_to_qimage(apply_spotlight(self._redacted, self.doc.items))
            self._spot_key = spot_key
        self.canvas.set_content(
            self._base_qimage, build_primitives(self.doc), self._lens_images(), self.doc.padding, self.doc.crop
        )
        view = self.doc.view
        size = f"{int(view.w)} x {int(view.h)} px"
        if self.doc.crop is not None:
            size += f" (recorte de {self.doc.image_size[0]} x {self.doc.image_size[1]})"
        self.info_label.setText(f"{self.doc.image_path.name} - {size} - {len(self.doc.items)} anotaciones")
        self.info_label.setToolTip(self.info_label.text())

    def _warn_missing_overlays(self, overlays: tuple[ImageOverlay, ...]) -> None:
        """Avisa (una vez por archivo) de las imagenes pegadas cuyo archivo ya no existe: no se dibujan."""
        for path in missing_overlays(overlays):
            if path not in self._warned_missing:
                self._warned_missing.add(path)
                self.statusMessage.emit(f"No se encontro la imagen pegada {path}: no se dibuja (volvio a aparecer = se muestra).")

    def _lens_images(self) -> dict[str, QImage]:
        """Recorte ampliado de cada lupa, tomado del bitmap YA pixelado. Se
        recalcula solo si cambio su origen, zoom o forma (mover el lente no cambia
        el recorte) o los pixelados."""
        assert self.doc is not None and self._redacted is not None
        images: dict[str, QImage] = {}
        for item in self.doc.items:
            if not isinstance(item, Magnifier):
                continue
            cache_key = (self._base_key, item.source, item.zoom, item.shape)
            cached = self._lens_cache.get(item.id)
            if cached is None or cached[0] != cache_key:
                crop = lens_crops(self._redacted, [item])[item.id]
                cached = (cache_key, pil_to_qimage(crop))
                self._lens_cache[item.id] = cached
            images[item.id] = cached[1]
        for stale in set(self._lens_cache) - set(images):
            del self._lens_cache[stale]
        return images

    # ------------------------------------------------------------------
    # Exportar
    # ------------------------------------------------------------------

    def _on_scale_clicked(self, factor: int) -> None:
        if self.doc is None:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self, f"Guardar captura escalada {factor}x", str(scaled_output_path(self.doc.image_path, factor)),
            "PNG (*.png)",
        )
        if chosen:
            self.scale_capture(factor, Path(chosen))

    def scale_capture(self, factor: int, output_path: Path) -> bool:
        """Guarda la captura original (sin anotaciones) escalada `factor` veces. No cambia el documento abierto.
        Devuelve True si se guardo."""
        if self.doc is None:
            return False
        source = self.doc.image_path
        start = time.perf_counter()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            size = save_upscaled(source, output_path, factor, sharpen=self.sharpen_action.isChecked())
        except GeometryError as exc:  # incluye AnnotateError
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo escalar", str(exc))
            return False
        QApplication.restoreOverrideCursor()
        before = self.doc.image_size
        self.statusMessage.emit(
            f"Escalada {factor}x ({before[0]} x {before[1]} -> {size[0]} x {size[1]} px) en {output_path} - "
            f"{time.perf_counter() - start:.2f}s. Abrela con Abrir... para anotarla"
        )
        return True

    def _on_export_clicked(self) -> None:
        if self.doc is None:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Exportar captura anotada", str(default_output_path(self.doc.image_path)), "PNG (*.png)"
        )
        if chosen:
            self.export_to(Path(chosen))

    def export_to(self, output_path: Path) -> bool:
        """Exporta el PNG (y el SVG si esta marcado). Si la ruta es la de la
        captura original pide escribir SOBRESCRIBIR y respalda la original.
        Devuelve True si se exporto."""
        if self.doc is None:
            return False
        doc = self.doc
        allow_overwrite = False
        backup_path: Path | None = None

        if output_path.resolve() == doc.image_path.resolve():
            if OverwriteConfirmDialog(self, subject="la captura original sin anotaciones").exec() != QDialog.Accepted:
                return False
            backup_path = output_path.with_name(f"{output_path.stem}.original{output_path.suffix}")
            try:
                shutil.copy2(output_path, backup_path)
            except OSError as exc:
                QMessageBox.critical(self, "No se pudo respaldar la captura original", str(exc))
                return False
            allow_overwrite = True

        start = time.perf_counter()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            export_png(doc, output_path, allow_overwrite=allow_overwrite)
            if self.svg_checkbox.isChecked():
                export_svg(doc, output_path.with_suffix(".svg"))
            if backup_path is not None:
                # la captura limpia ahora es el respaldo: se sigue editando contra ella
                doc.image_path = backup_path
            if doc.items:
                save_doc(doc)
            self.controller.stack.setClean()
        except GeometryError as exc:  # incluye AnnotateError
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo exportar", str(exc))
            return False
        QApplication.restoreOverrideCursor()

        elapsed = time.perf_counter() - start
        extra = f" - original respaldada en {backup_path}" if backup_path else ""
        needed = required_padding(doc)
        if needed > doc.padding:
            extra += f" - Aviso: algo se recorta en el borde; agrega {needed} px de margen"
        self.statusMessage.emit(f"Exportado en {output_path} - {elapsed:.2f}s{extra}")
        self.refresh()
        return True
