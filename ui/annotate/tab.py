"""Pestana "Anotar": abre o pega una captura, la muestra con sus anotaciones y
la exporta. Las herramientas interactivas llegan en la fase 4."""

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
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.annotate.errors import AnnotateError
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import AnnotationDoc
from core.annotate.primitives import build_primitives
from core.annotate.raster import apply_redactions, load_image
from core.annotate.svg import default_output_path, export_png, export_svg
from core.geometry import SUPPORTED_PHOTO_SUFFIXES, GeometryError
from ui.annotate.canvas import AnnotateCanvas
from ui.dialogs import OverwriteConfirmDialog


def captures_dir() -> Path:
    """Carpeta donde se guardan las capturas pegadas desde el portapapeles."""
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return Path(pictures or Path.home()) / "Cover Studio"


def pil_to_qimage(img: Image.Image) -> QImage:
    rgba = img.convert("RGBA")
    qimage = QImage(rgba.tobytes("raw", "RGBA"), rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888)
    return qimage.copy()  # desacopla el QImage del buffer temporal de Python


class AnnotateTab(QWidget):
    statusMessage = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc: AnnotationDoc | None = None
        self.base_image: Image.Image | None = None

        self.open_btn = QPushButton("Abrir...")
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.paste_btn = QPushButton("Pegar (CTRL + V)")
        self.paste_btn.clicked.connect(self.paste_capture)
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
        bar.addWidget(self.export_btn)

        self.canvas = AnnotateCanvas()

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.canvas, stretch=1)

        paste_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self)
        paste_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        paste_shortcut.activated.connect(self.paste_capture)

    # ------------------------------------------------------------------
    # Cargar
    # ------------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Abrir captura", "", "Imagenes (*.png *.jpg *.jpeg *.webp)"
        )
        if path_str:
            self.load_capture(Path(path_str))

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

    def load_capture(self, path: Path) -> None:
        """Abre una captura; si junto a ella hay un proyecto de anotaciones
        (.anotar.json) del mismo tamano, lo recupera."""
        try:
            image = load_image(path)
        except AnnotateError as exc:
            QMessageBox.critical(self, "No se pudo abrir la captura", str(exc))
            return

        doc = AnnotationDoc(path, image.size)
        note = ""
        sidecar = sidecar_path(path)
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
        self.export_btn.setEnabled(True)
        self.refresh()
        self.statusMessage.emit(f"Captura abierta: {path}{note}")

    def refresh(self) -> None:
        """Vuelve a pintar la captura con el pixelado y las anotaciones actuales."""
        if self.doc is None or self.base_image is None:
            self.canvas.set_content(None, [])
            self.info_label.setText("Sin captura.")
            return
        redacted = apply_redactions(self.base_image, self.doc.items)
        self.canvas.set_content(pil_to_qimage(redacted), build_primitives(self.doc))
        w, h = self.doc.image_size
        self.info_label.setText(f"{self.doc.image_path.name} - {w} x {h} px - {len(self.doc.items)} anotaciones")

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
        except GeometryError as exc:  # incluye AnnotateError
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "No se pudo exportar", str(exc))
            return False
        QApplication.restoreOverrideCursor()

        elapsed = time.perf_counter() - start
        extra = f" - original respaldada en {backup_path}" if backup_path else ""
        self.statusMessage.emit(f"Exportado en {output_path} - {elapsed:.2f}s{extra}")
        self.refresh()
        return True
