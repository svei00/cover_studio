import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QCloseEvent, QColor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate.bounds import required_padding
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import AnnotationDoc, ArrowSide, Marker, Rect, StepBadge
from ui.annotate import tab as tab_module
from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _capture(path: Path, size=(800, 500)) -> Path:
    Image.new("RGB", size, (40, 60, 90)).save(path)
    return path


@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(_capture(tmp_path / "cap.png"))
    QApplication.processEvents()
    return t


@pytest.fixture
def errors(monkeypatch):
    calls = []

    class Stub:
        @staticmethod
        def critical(*args, **kwargs):
            calls.append(args)

    monkeypatch.setattr(tab_module, "QMessageBox", Stub)
    return calls


def _mouse(canvas, kind, pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def mdrag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton)


def draw_marker(tab, a=(300.0, 200.0), b=(400.0, 250.0)):
    tab.tool_buttons[Tool.MARKER].click()
    mdrag(tab.canvas, a, b)


# --- margen extra ----------------------------------------------------------

def test_margen_desde_el_panel_se_aplica_se_ve_y_se_deshace(tab):
    sin_margen = tab.canvas.view_layout()[0]
    tab.panel._padding_spin.setValue(30)
    assert tab.doc.padding == 30
    assert tab.canvas.view_layout()[0] < sin_margen  # el margen tambien ocupa lugar en pantalla
    tab.controller.undo()
    assert tab.doc.padding == 0 and tab.panel._padding_spin.value() == 0


def test_cambios_seguidos_de_margen_son_un_solo_paso(tab):
    for v in (10, 20, 30):
        tab.panel._padding_spin.setValue(v)
    assert tab.doc.padding == 30 and tab.controller.stack.count() == 1


def test_las_coordenadas_siguen_siendo_correctas_con_margen(tab):
    tab.panel._padding_spin.setValue(40)
    for p in [(0.0, 0.0), (123.5, 77.25), (799.0, 499.0)]:
        v = tab.canvas.image_to_view(p)
        assert tab.canvas.view_to_image(v) == pytest.approx(p, abs=1e-6)


def test_se_puede_dibujar_y_seleccionar_con_margen(tab):
    tab.panel._padding_spin.setValue(40)
    draw_marker(tab)
    item = tab.doc.items[0]
    assert (item.rect.x, item.rect.y) == pytest.approx((300, 200), abs=1)
    mdrag(tab.canvas, (300.0, 225.0), (330.0, 225.0))  # agarra el borde izquierdo y lo mueve
    assert tab.doc.items[0].rect.x == pytest.approx(330, abs=1)


def test_un_clic_en_el_margen_se_recorta_al_borde_de_la_imagen(tab):
    tab.panel._padding_spin.setValue(40)
    tab.tool_buttons[Tool.MARKER].click()
    mdrag(tab.canvas, (-20.0, 100.0), (100.0, 200.0))
    assert tab.doc.items[0].rect.x == 0


def test_el_margen_se_exporta(tab, tmp_path):
    tab.panel._padding_spin.setValue(25)
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    assert Image.open(out).size == (850, 550)


# --- escala de trazo --------------------------------------------------------

def test_escala_manual_y_automatica(tab):
    assert tab.doc.style_scale is None and tab.panel._scale_auto.isChecked()
    auto = tab.controller.scale()
    tab.panel._scale_auto.setChecked(False)
    assert tab.doc.style_scale == pytest.approx(auto, abs=0.01)
    tab.panel._scale_spin.setValue(2.0)
    assert tab.doc.style_scale == 2.0 and tab.controller.scale() == 2.0
    tab.panel._scale_auto.setChecked(True)
    assert tab.doc.style_scale is None


def test_cambios_seguidos_de_escala_son_un_solo_paso_de_deshacer(tab):
    tab.panel._scale_auto.setChecked(False)
    tab.panel._scale_spin.setValue(2.0)
    tab.panel._scale_spin.setValue(3.0)
    assert tab.doc.style_scale == 3.0 and tab.controller.stack.count() == 1
    tab.controller.undo()
    assert tab.doc.style_scale is None  # de vuelta a automatica


def test_deshacer_la_escala_cuando_hay_pasos_separados(tab):
    tab.controller.set_style_scale(2.0)
    tab.controller.set_padding(10)  # otra propiedad: corta la fusion
    tab.controller.set_style_scale(3.0)
    assert tab.controller.stack.count() == 3
    tab.controller.undo()
    assert tab.doc.style_scale == 2.0 and tab.doc.padding == 10
    tab.controller.undo()
    assert tab.doc.padding == 0 and tab.doc.style_scale == 2.0


def test_la_escala_cambia_el_trazo_dibujado(tab):
    draw_marker(tab)
    from core.annotate.primitives import PRect, build_primitives

    def ancho_rojo():
        return next(p for p in build_primitives(tab.doc) if isinstance(p, PRect) and p.stroke == "#621132").width

    antes = ancho_rojo()
    tab.controller.set_style_scale(tab.controller.scale() * 2)
    assert ancho_rojo() == pytest.approx(antes * 2)


# --- aviso de recorte -------------------------------------------------------

def test_avisa_cuando_el_resplandor_se_recorta_y_el_boton_agrega_el_margen(tab):
    draw_marker(tab, (0.0, 200.0), (100.0, 250.0))
    tab.controller.select(None)
    needed = required_padding(tab.doc)
    assert needed > 0
    assert not tab.panel._clip_notice.isHidden() and str(needed) in tab.panel._clip_btn.text()
    tab.panel._clip_btn.click()
    assert tab.doc.padding == needed
    assert tab.panel._clip_notice.isHidden() and tab.panel._clip_btn.isHidden()


def test_sin_recorte_no_hay_aviso(tab):
    draw_marker(tab)
    tab.controller.select(None)
    assert tab.panel._clip_notice.isHidden()


def test_exportar_con_recorte_avisa_en_la_barra_de_estado(tab, tmp_path):
    draw_marker(tab, (0.0, 200.0), (100.0, 250.0))
    mensajes = []
    tab.statusMessage.connect(mensajes.append)
    tab.export_to(tmp_path / "a.png")
    assert "Aviso" in mensajes[-1]
    tab.controller.set_padding(required_padding(tab.doc))
    tab.export_to(tmp_path / "b.png")
    assert "Aviso" not in mensajes[-1]


# --- estado sin guardar -----------------------------------------------------

def test_dirty_sigue_a_la_pila_de_deshacer(tab):
    estados = []
    tab.dirtyChanged.connect(estados.append)
    assert not tab.is_dirty()
    draw_marker(tab)
    assert tab.is_dirty() and estados[-1] is True
    tab.controller.undo()
    assert not tab.is_dirty() and estados[-1] is False  # volver al estado guardado lo deja limpio


def test_guardar_proyecto_escribe_el_json_y_deja_limpio(tab, tmp_path):
    draw_marker(tab)
    assert tab.save_project() is True
    assert not tab.is_dirty()
    assert load_doc(sidecar_path(tmp_path / "cap.png")).items == tab.doc.items


def test_exportar_deja_limpio(tab, tmp_path):
    draw_marker(tab)
    tab.export_to(tmp_path / "salida.png")
    assert not tab.is_dirty()


def test_el_margen_y_la_escala_tambien_ensucian(tab):
    tab.panel._padding_spin.setValue(10)
    assert tab.is_dirty()


def test_guardar_sin_captura_no_hace_nada(qapp):
    t = AnnotateTab()
    assert t.save_project() is False
    t.copy_to_clipboard()  # no truena


# --- confirmaciones ---------------------------------------------------------

def _otra(tmp_path):
    return _capture(tmp_path / "otra.png", (400, 300))


def test_cancelar_no_abre_la_otra_captura_ni_pierde_nada(tab, tmp_path, monkeypatch):
    draw_marker(tab)
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "cancel")
    tab.load_capture(_otra(tmp_path))
    assert tab.doc.image_path == tmp_path / "cap.png" and len(tab.doc.items) == 1 and tab.is_dirty()


def test_descartar_abre_la_otra_captura(tab, tmp_path, monkeypatch):
    draw_marker(tab)
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "discard")
    tab.load_capture(_otra(tmp_path))
    assert tab.doc.image_path == tmp_path / "otra.png" and tab.doc.items == []
    assert not sidecar_path(tmp_path / "cap.png").exists()


def test_guardar_escribe_el_proyecto_y_luego_abre(tab, tmp_path, monkeypatch):
    draw_marker(tab)
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "save")
    tab.load_capture(_otra(tmp_path))
    assert tab.doc.image_path == tmp_path / "otra.png"
    assert len(load_doc(sidecar_path(tmp_path / "cap.png")).items) == 1


def test_sin_cambios_no_pregunta_nada(tab, tmp_path, monkeypatch):
    def no_debe_llamarse(self):
        raise AssertionError("no habia cambios sin guardar")

    monkeypatch.setattr(AnnotateTab, "_ask_discard", no_debe_llamarse)
    tab.load_capture(_otra(tmp_path))
    assert tab.doc.image_path == tmp_path / "otra.png"


def test_guardar_que_falla_no_abre_la_otra_captura(tab, tmp_path, monkeypatch, errors):
    draw_marker(tab)
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "save")
    monkeypatch.setattr(tab_module, "save_doc", lambda doc: (_ for _ in ()).throw(tab_module.AnnotateError("sin permiso")))
    tab.load_capture(_otra(tmp_path))
    assert tab.doc.image_path == tmp_path / "cap.png" and len(errors) == 1


# --- ventana principal ------------------------------------------------------

def test_la_pestana_muestra_asterisco_y_cerrar_pregunta(qapp, tmp_path, monkeypatch):
    from ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    t = w.annotate_tab
    t.load_capture(_capture(tmp_path / "cap.png"))
    idx = w.tabs.indexOf(t)
    assert w.tabs.tabText(idx) == "Anotar"
    t.tool_buttons[Tool.STEP].click()
    mdrag(t.canvas, (100.0, 100.0), (100.0, 100.0))
    assert w.tabs.tabText(idx) == "Anotar *"

    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "cancel")
    event = QCloseEvent()
    w.closeEvent(event)
    assert not event.isAccepted()

    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "discard")
    event = QCloseEvent()
    w.closeEvent(event)
    assert event.isAccepted()

    t.save_project()
    assert w.tabs.tabText(idx) == "Anotar"


# --- abrir proyecto y portapapeles --------------------------------------------

def test_abrir_un_proyecto_restaura_captura_y_anotaciones(qapp, tmp_path):
    cap = _capture(tmp_path / "cap.png")
    items = [Marker("a1", Rect(10, 10, 50, 30), ArrowSide.LEFT), StepBadge("a2", (200.0, 100.0), 1)]
    project = save_doc(AnnotationDoc(cap, (800, 500), items, padding=15))
    t = AnnotateTab()
    t.open_project(project)
    assert t.doc.image_path == cap and t.doc.items == items and t.doc.padding == 15
    assert not t.is_dirty()


def test_abrir_un_proyecto_roto_muestra_error_y_no_cambia_nada(qapp, tmp_path, errors):
    malo = tmp_path / "x.anotar.json"
    malo.write_text("{ no es json", encoding="utf-8")
    t = AnnotateTab()
    t.open_project(malo)
    assert t.doc is None and len(errors) == 1


def test_proyecto_cuya_captura_ya_no_existe_avisa(qapp, tmp_path, errors):
    project = save_doc(AnnotationDoc(tmp_path / "desaparecida.png", (800, 500), []))
    t = AnnotateTab()
    t.open_project(project)
    assert t.doc is None and len(errors) == 1


def test_copiar_deja_la_imagen_anotada_en_el_portapapeles(tab):
    tab.panel._padding_spin.setValue(20)
    draw_marker(tab, (100.0, 100.0), (300.0, 180.0))
    QGuiApplication.clipboard().clear()
    mensajes = []
    tab.statusMessage.connect(mensajes.append)
    tab.copy_to_clipboard()
    image = QGuiApplication.clipboard().image()
    assert (image.width(), image.height()) == (840, 540)
    assert "Copiada" in mensajes[-1] and "840 x 540" in mensajes[-1]
    # el borde izquierdo del marcador (con el margen de 20 px) es rojo oscuro
    r = tab.doc.items[0].rect
    px = QColor(image.pixel(round(r.x) + 20, round(r.y + r.h / 2) + 20))
    assert abs(px.red() - 0x62) < 40 and abs(px.green() - 0x11) < 40


# --- la pantalla muestra lo que se exporta -------------------------------------

def _pixel(tab, image_pt):
    img = tab.canvas.grab().toImage()
    v = tab.canvas.image_to_view(image_pt)
    return QColor(img.pixel(int(v.x()), int(v.y())))


def test_sin_margen_el_resplandor_se_recorta_en_pantalla_como_en_la_exportacion(tab):
    draw_marker(tab, (0.0, 200.0), (100.0, 250.0))
    tab.controller.select(None)
    fuera = _pixel(tab, (-6.0, 225.0))  # justo a la izquierda del borde de la imagen
    assert fuera.name().lower() == "#202020"  # el fondo del lienzo: nada de resplandor fuera de la imagen


def test_con_margen_el_resplandor_se_ve_en_el_margen(tab):
    draw_marker(tab, (0.0, 200.0), (100.0, 250.0))
    tab.controller.select(None)
    tab.controller.set_padding(required_padding(tab.doc))
    dentro = _pixel(tab, (-6.0, 225.0))
    assert dentro.name().lower() != "#1b3350" and dentro.red() > 0x1B + 15  # navy del margen + resplandor dorado
