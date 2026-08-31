"""Pestana "Anotar": abre o pega una captura, permite anotarla con el mouse
(marcador, flecha, paso, texto, pixelado) con deshacer/rehacer, y la exporta."""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.annotate.bounds import required_padding
from core.annotate.errors import AnnotateError
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import AnnotationDoc, Magnifier, Redaction
from core.annotate.primitives import build_primitives
from core.annotate.raster import apply_redactions, lens_crops, load_image
from core.annotate.svg import default_output_path, export_png, export_svg, render_bytes
from core.geometry import SUPPORTED_PHOTO_SUFFIXES, GeometryError
from ui.annotate.canvas import AnnotateCanvas
from ui.annotate.controller import EditController, Tool
from ui.annotate.panel import PropertiesPanel
from ui.dialogs import OverwriteConfirmDialog


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
    (Tool.ARROW, "Flecha", "Flecha suelta: arrastra del inicio a la punta"),
    (Tool.STEP, "Paso", "Circulo numerado: clic donde va; la numeracion continua sola"),
    (Tool.TEXT, "Texto", "Etiqueta de texto: clic donde va y escribe en el panel"),
    (Tool.REDACT, "Pixelar", "Pixela una zona para anonimizar (RFC, nombres, UUID)"),
    (Tool.LENS, "Lupa", "Amplia una zona en un lente aparte: arrastra sobre lo que quieres ampliar"),
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
        self.svg_checkbox = QCheckBox("Guardar tambien el SVG")
        self.info_label = QLabel("Sin captura.")

        bar = QHBoxLayout()
        bar.addWidget(self.open_btn)
        bar.addWidget(self.paste_btn)
        bar.addWidget(self.info_label, stretch=1)
        bar.addWidget(self.svg_checkbox)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.export_btn)

        self.controller = EditController(self)
        self.canvas = AnnotateCanvas()
        self.canvas.set_controller(self.controller)
        self.panel = PropertiesPanel(self.controller)
        self._base_key: tuple | None = None
        self._base_qimage: QImage | None = None
        self._redacted: Image.Image | None = None
        self._lens_cache: dict[str, tuple[tuple, QImage]] = {}

        tools = QHBoxLayout()
        self.tool_buttons: dict[Tool, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for tool, label, tip in TOOL_BUTTONS:
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked, t=tool: self.controller.set_tool(t))
            group.addButton(button)
            self.tool_buttons[tool] = button
            tools.addWidget(button)
        self.tool_buttons[Tool.SELECT].setChecked(True)
        tools.addSpacing(16)
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
        tools.addStretch(1)

        body = QHBoxLayout()
        body.addWidget(self.canvas, stretch=1)
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
                          (QKeySequence.StandardKey.Undo, self.controller.undo),
                          (QKeySequence.StandardKey.Redo, self.controller.redo),
                          (QKeySequence.StandardKey.Save, self.save_project),
                          (QKeySequence.StandardKey.Copy, self.copy_to_clipboard)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _on_clean_changed(self, clean: bool) -> None:
        self.dirtyChanged.emit(not clean)

    def _on_tool_changed(self, tool: Tool) -> None:
        self.tool_buttons[tool].setChecked(True)

    def _update_history_buttons(self) -> None:
        stack = self.controller.stack
        self.undo_btn.setEnabled(stack.canUndo())
        self.redo_btn.setEnabled(stack.canRedo())
        self.delete_btn.setEnabled(self.controller.selected_item() is not None)

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

    def paste_capture(self) -> None:
        """Pega la imagen del portapapeles (se guarda en Imagenes/Cover Studio)
        o, si se copio un archivo de imagen, lo abre."""
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES:
                    self.load_capture(path)
                    return
        if mime is not None and mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                folder = captures_dir()
                path = folder / f"captura-{datetime.now():%Y%m%d-%H%M%S}.png"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    QMessageBox.critical(self, "No se pudo guardar la captura pegada", str(exc))
                    return
                if not image.save(str(path), "PNG"):
                    QMessageBox.critical(self, "No se pudo guardar la captura pegada", str(path))
                    return
                self.load_capture(path)
                self.statusMessage.emit(f"Captura pegada y guardada en {path}")
                return
        self.statusMessage.emit("No hay una imagen en el portapapeles.")

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

        doc = AnnotationDoc(path, image.size)
        note = ""
        sidecar = project or sidecar_path(path)
        if sidecar.exists():
            try:
                saved = load_doc(sidecar)
                if tuple(saved.image_size) == image.size:
                    doc = AnnotationDoc(path, image.size, saved.items, saved.style_scale, saved.padding)
                    note = f" ({len(doc.items)} anotaciones recuperadas)"
                else:
                    note = " (el proyecto guardado era de otra imagen; se ignoro)"
            except AnnotateError as exc:
                note = f" (no se pudo leer el proyecto guardado: {exc})"

        self.base_image = image
        self.doc = doc
        self._base_key = None
        self.export_btn.setEnabled(True)
        for button in self.tool_buttons.values():
            button.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self.controller.set_doc(doc)
        self.statusMessage.emit(f"Captura abierta: {path}{note}")

    def refresh(self) -> None:
        """Vuelve a pintar la captura con el pixelado y las anotaciones actuales."""
        if self.doc is None or self.base_image is None:
            self.canvas.set_content(None, [])
            self.info_label.setText("Sin captura.")
            return
        # el bitmap pixelado solo se recalcula si cambiaron los pixelados
        key = tuple(i for i in self.doc.items if isinstance(i, Redaction))
        if key != self._base_key or self._base_qimage is None or self._redacted is None:
            self._redacted = apply_redactions(self.base_image, self.doc.items)
            self._base_qimage = pil_to_qimage(self._redacted)
            self._base_key = key
            self._lens_cache.clear()
        self.canvas.set_content(
            self._base_qimage, build_primitives(self.doc), self._lens_images(), self.doc.padding
        )
        w, h = self.doc.image_size
        self.info_label.setText(f"{self.doc.image_path.name} - {w} x {h} px - {len(self.doc.items)} anotaciones")

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
