import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDropEvent, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QDialog

from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import AnnotationDoc, Marker, Rect, TextLabel
from ui.annotate import tab as tab_module
from ui.annotate.canvas import AnnotateCanvas
from ui.annotate.tab import AnnotateTab, pil_to_qimage


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp):
    return AnnotateTab()


@pytest.fixture
def errors(monkeypatch):
    """Registra los QMessageBox.critical en vez de abrir un dialogo."""
    calls = []

    class Stub:
        @staticmethod
        def critical(*args, **kwargs):
            calls.append(args)

    monkeypatch.setattr(tab_module, "QMessageBox", Stub)
    return calls


def _png(path: Path, size=(320, 200)) -> Path:
    Image.new("RGB", size, (40, 90, 140)).save(path)
    return path


def _messages(tab):
    got = []
    tab.statusMessage.connect(got.append)
    return got


def test_load_capture_valida_activa_exportar_y_muestra_info(tab, tmp_path):
    tab.load_capture(_png(tmp_path / "cap.png"))
    assert tab.doc is not None and tab.doc.image_size == (320, 200)
    assert tab.export_btn.isEnabled()
    assert "320 x 200" in tab.info_label.text()


def test_load_capture_invalida_muestra_error_y_no_cambia_el_estado(tab, tmp_path, errors):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"no soy imagen")
    tab.load_capture(roto)
    assert tab.doc is None and not tab.export_btn.isEnabled()
    assert len(errors) == 1


def test_load_capture_recupera_el_proyecto_guardado(tab, tmp_path):
    cap = _png(tmp_path / "cap.png")
    items = [Marker("m", Rect(10, 10, 50, 20)), TextLabel("t", (5.0, 5.0), "hola")]
    save_doc(AnnotationDoc(cap, (320, 200), items, padding=7))
    tab.load_capture(cap)
    assert tab.doc.items == items and tab.doc.padding == 7


def test_load_capture_ignora_un_proyecto_de_otro_tamano(tab, tmp_path):
    cap = _png(tmp_path / "cap.png")
    save_doc(AnnotationDoc(cap, (999, 999), [Marker("m", Rect(1, 1, 5, 5))]))
    mensajes = _messages(tab)
    tab.load_capture(cap)
    assert tab.doc.items == []
    assert "otra imagen" in mensajes[-1]


def test_export_to_escribe_png_y_proyecto_sin_tocar_el_original(tab, tmp_path):
    cap = _png(tmp_path / "cap.png")
    antes = cap.read_bytes()
    tab.load_capture(cap)
    tab.doc.items.append(Marker("m", Rect(50, 50, 80, 40)))
    out = tmp_path / "cap-anotada.png"
    assert tab.export_to(out) is True
    assert out.exists() and cap.read_bytes() == antes
    assert sidecar_path(cap).exists()


def test_export_to_sin_anotaciones_no_deja_proyecto(tab, tmp_path):
    cap = _png(tmp_path / "cap.png")
    tab.load_capture(cap)
    assert tab.export_to(tmp_path / "salida.png") is True
    assert not sidecar_path(cap).exists()


def test_export_to_guarda_el_svg_si_esta_marcado(tab, tmp_path):
    tab.load_capture(_png(tmp_path / "cap.png"))
    tab.svg_checkbox.setChecked(True)
    tab.export_to(tmp_path / "salida.png")
    assert (tmp_path / "salida.svg").exists()


class _Dialog:
    result = QDialog.Rejected

    def __init__(self, *args, **kwargs):
        pass

    def exec(self):
        return self.result


def test_export_to_sobre_el_original_rechazado_no_cambia_nada(tab, tmp_path, monkeypatch):
    cap = _png(tmp_path / "cap.png")
    antes = cap.read_bytes()
    tab.load_capture(cap)
    monkeypatch.setattr(tab_module, "OverwriteConfirmDialog", _Dialog)
    assert tab.export_to(cap) is False
    assert cap.read_bytes() == antes
    assert not (tmp_path / "cap.original.png").exists()


def test_export_to_sobre_el_original_aceptado_respalda_y_sigue_editando_el_respaldo(tab, tmp_path, monkeypatch):
    cap = _png(tmp_path / "cap.png")
    antes = cap.read_bytes()
    tab.load_capture(cap)
    tab.doc.items.append(Marker("m", Rect(50, 50, 80, 40)))

    class Si(_Dialog):
        result = QDialog.Accepted

    monkeypatch.setattr(tab_module, "OverwriteConfirmDialog", Si)
    assert tab.export_to(cap) is True
    backup = tmp_path / "cap.original.png"
    assert backup.read_bytes() == antes
    assert cap.read_bytes() != antes
    assert tab.doc.image_path == backup
    assert load_doc(sidecar_path(backup)).image_path == backup


def test_pegar_sin_imagen_avisa_y_no_truena(tab, qapp):
    QGuiApplication.clipboard().clear()
    mensajes = _messages(tab)
    tab.paste_capture()
    assert "No hay una imagen" in mensajes[-1] and tab.doc is None


def test_pegar_imagen_la_guarda_y_la_abre(tab, qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(tab_module, "captures_dir", lambda: tmp_path / "capturas")
    image = QImage(64, 48, QImage.Format_RGB32)
    image.fill(QColor("#336699"))
    QGuiApplication.clipboard().setImage(image)
    tab.paste_capture()
    assert tab.doc is not None and tab.doc.image_size == (64, 48)
    assert tab.doc.image_path.parent == tmp_path / "capturas" and tab.doc.image_path.exists()


def test_pegar_un_archivo_copiado_lo_abre(tab, qapp, tmp_path):
    cap = _png(tmp_path / "cap.png")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(cap))])
    QGuiApplication.clipboard().setMimeData(mime)
    tab.paste_capture()
    assert tab.doc is not None and tab.doc.image_path == cap


def test_pil_to_qimage_conserva_tamano_y_color():
    qimage = pil_to_qimage(Image.new("RGBA", (10, 6), (200, 100, 50, 255)))
    assert (qimage.width(), qimage.height()) == (10, 6)
    assert QColor(qimage.pixel(3, 3)).getRgb()[:3] == (200, 100, 50)


def test_canvas_ajusta_la_imagen_a_la_ventana_y_la_centra(qapp):
    canvas = AnnotateCanvas()
    canvas.resize(500, 300)
    canvas.set_content(QImage(1000, 500, QImage.Format_RGB32), [])
    scale, ox, oy = canvas.view_layout()
    assert scale < 1
    assert ox >= 0 and oy >= 0
    assert 1000 * scale <= 500 and 500 * scale <= 300


def test_canvas_no_amplia_mas_de_dos_veces(qapp):
    canvas = AnnotateCanvas()
    canvas.resize(2000, 2000)
    canvas.set_content(QImage(100, 100, QImage.Format_RGB32), [])
    assert canvas.view_layout()[0] == 2.0


def test_canvas_pinta_las_anotaciones_sobre_la_captura(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(900, 600)
    t.load_capture(_png(tmp_path / "cap.png"))
    t.doc.items.append(TextLabel("t", (20.0, 20.0), "Hola", bg="#FFFFFF", border=None, color="#000000"))
    t.refresh()
    img = t.canvas.grab().toImage()
    assert img.width() > 0
    scale, ox, oy = t.canvas.view_layout()
    px = QColor(img.pixel(int(ox + 25 * scale), int(oy + 25 * scale)))
    assert px.red() > 200 and px.green() > 200  # el fondo blanco de la etiqueta


def test_main_window_tiene_las_dos_pestanas_y_enruta_el_arrastre(qapp, tmp_path):
    from ui.main_window import MainWindow

    w = MainWindow()
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Portada", "Anotar"]
    cap = _png(tmp_path / "cap.png")

    def drop():
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(cap))])
        w.dropEvent(QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))

    w.tabs.setCurrentWidget(w.annotate_tab)
    drop()
    assert w.annotate_tab.doc is not None and w.photo_path is None

    w.tabs.setCurrentIndex(0)
    drop()
    assert w.photo_path == cap
