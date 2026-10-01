"""Atajos de la pestana Anotar (Ctrl+V pegar captura, Ctrl+C copiar, Ctrl+Z...): deben funcionar con el foco donde sea
mientras la pestana este visible. Bug: al cambiar de pestana con el mouse el foco se queda en la barra de pestanas (fuera
del widget) y los atajos, limitados a lo que hay dentro, no hacian nada hasta hacer clic en la captura."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.annotate.tab import AnnotateTab
from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.activateWindow()
    QApplication.processEvents()
    if QApplication.activeWindow() is not w:
        pytest.skip("esta plataforma no activa la ventana: sin ventana activa Qt no despacha atajos")
    return w


def _imagen_en_el_portapapeles():
    image = QImage(320, 180, QImage.Format_RGB32)
    image.fill(0xFF2060A0)
    QGuiApplication.clipboard().setImage(image)


def test_todos_los_atajos_de_la_pestana_son_de_la_ventana_y_no_de_lo_que_hay_dentro(qapp):
    shortcuts = AnnotateTab().findChildren(QShortcut)
    assert len(shortcuts) >= 9
    assert {s.context() for s in shortcuts} == {Qt.WindowShortcut}


def test_pegar_con_el_foco_en_la_barra_de_pestanas_abre_la_captura(window, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.annotate.tab.captures_dir", lambda: tmp_path / "capturas")
    _imagen_en_el_portapapeles()
    window.tabs.setCurrentIndex(1)                       # como al hacer clic en la cabecera "Anotar"
    window.tabs.tabBar().setFocus()
    QApplication.processEvents()
    assert window.annotate_tab.doc is None
    QTest.keyClick(window.tabs.tabBar(), Qt.Key_V, Qt.ControlModifier)
    QTest.qWait(100)
    assert window.annotate_tab.doc is not None and window.annotate_tab.doc.image_size == (320, 180)


def test_copiar_con_el_foco_en_la_barra_de_pestanas_copia_la_captura_anotada(window, tmp_path):
    Image.new("RGB", (400, 250), (255, 255, 255)).save(tmp_path / "c.png")
    window.annotate_tab.load_capture(tmp_path / "c.png")
    window.tabs.setCurrentIndex(1)
    window.tabs.tabBar().setFocus()
    QGuiApplication.clipboard().clear()
    QTest.keyClick(window.tabs.tabBar(), Qt.Key_C, Qt.ControlModifier)
    QTest.qWait(200)
    image = QGuiApplication.clipboard().image()
    assert not image.isNull() and (image.width(), image.height()) == (400, 250)


def test_en_la_pestana_portada_los_atajos_de_anotar_no_se_disparan_y_el_titulo_pega_su_texto(window):
    _imagen_en_el_portapapeles()
    window.tabs.setCurrentIndex(0)
    window.title_edit.setFocus()
    QGuiApplication.clipboard().setText("Titulo pegado")
    QTest.keyClick(window.title_edit, Qt.Key_V, Qt.ControlModifier)
    QTest.qWait(100)
    assert window.title_edit.toPlainText() == "Titulo pegado" and window.annotate_tab.doc is None


def test_el_editor_de_texto_de_anotar_sigue_pegando_texto_y_no_una_captura(window, tmp_path):
    from core.annotate.model import TextLabel

    Image.new("RGB", (400, 250), (255, 255, 255)).save(tmp_path / "c.png")
    window.annotate_tab.load_capture(tmp_path / "c.png")
    window.tabs.setCurrentIndex(1)
    window.annotate_tab.doc.items.append(TextLabel("t1", (50.0, 50.0), "Hola"))
    window.annotate_tab.controller.select("t1")
    QApplication.processEvents()
    editor = window.annotate_tab.panel._text_edit
    editor.setFocus()
    editor.selectAll()
    QGuiApplication.clipboard().setText("otro texto")
    QTest.keyClick(editor, Qt.Key_V, Qt.ControlModifier)
    QTest.qWait(100)
    assert editor.toPlainText() == "otro texto" and window.annotate_tab.doc.image_size == (400, 250)
