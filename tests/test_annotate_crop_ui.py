import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate.model import ArrowSide, Marker, Rect
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


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def press(canvas, p):
    _mouse(canvas, QEvent.MouseButtonPress, p)


def move(canvas, p):
    _mouse(canvas, QEvent.MouseMove, p, buttons=Qt.LeftButton, button=Qt.NoButton)


def release(canvas, p):
    _mouse(canvas, QEvent.MouseButtonRelease, p, buttons=Qt.NoButton)


def drag(canvas, a, b):
    press(canvas, a)
    move(canvas, b)
    release(canvas, b)


def crop_with_tool(tab, a=(100, 50), b=(500, 350)):
    tab.tool_buttons[Tool.CROP].click()
    drag(tab.canvas, a, b)
    return tab.doc.crop


def test_el_boton_recortar_existe_y_activa_la_herramienta(tab):
    assert Tool.CROP in tab.tool_buttons and tab.tool_buttons[Tool.CROP].isEnabled()
    tab.tool_buttons[Tool.CROP].click()
    assert tab.controller.tool is Tool.CROP


def test_arrastrar_recorta_y_se_puede_deshacer_y_rehacer(tab):
    assert crop_with_tool(tab) == Rect(100, 50, 400, 300)
    assert tab.controller.stack.count() == 1
    tab.controller.undo()
    assert tab.doc.crop is None
    tab.controller.redo()
    assert tab.doc.crop == Rect(100, 50, 400, 300)


def test_la_herramienta_sigue_activa_para_ajustar_las_asas(tab):
    crop_with_tool(tab)
    assert tab.controller.tool is Tool.CROP
    # asa NE del recorte: (500, 50)
    drag(tab.canvas, (500, 50), (450, 100))
    assert tab.doc.crop == Rect(100, 100, 350, 250)
    assert tab.controller.stack.count() == 2   # cada ajuste es su propio paso


def test_con_la_herramienta_se_ve_la_imagen_completa_y_al_salir_solo_el_recorte(tab):
    c = tab.canvas
    crop_with_tool(tab)
    scale, ox, oy = c.view_layout()
    assert (c.image_to_view((0, 0)).x(), c.image_to_view((0, 0)).y()) == pytest.approx((ox, oy))
    tab.controller.set_tool(Tool.SELECT)
    scale2, ox2, oy2 = c.view_layout()
    assert scale2 > scale   # el recorte es mas pequeno: se ve mas grande
    top_left = c.image_to_view((100, 50))
    assert (top_left.x(), top_left.y()) == pytest.approx((ox2, oy2))
    # la conversion de ida y vuelta se conserva
    back = c.view_to_image(c.image_to_view((321.0, 123.0)))
    assert back == pytest.approx((321.0, 123.0))


def test_las_anotaciones_se_dibujan_en_coordenadas_de_la_fuente_con_recorte(tab):
    crop_with_tool(tab)
    tab.controller.set_tool(Tool.SELECT)
    tab.tool_buttons[Tool.MARKER_PLAIN].click()
    drag(tab.canvas, (150, 100), (250, 160))
    marker = tab.doc.items[0]
    assert isinstance(marker, Marker)
    assert marker.rect.x == pytest.approx(150, abs=1) and marker.rect.y == pytest.approx(100, abs=1)
    assert marker.rect.w == pytest.approx(100, abs=1)


def test_un_arrastre_minusculo_no_cambia_ni_quita_el_recorte(tab):
    crop_with_tool(tab)
    steps = tab.controller.stack.count()
    drag(tab.canvas, (300, 200), (303, 202))
    assert tab.doc.crop == Rect(100, 50, 400, 300)
    assert tab.controller.stack.count() == steps


def test_sin_recorte_las_asas_estan_en_las_esquinas_de_la_imagen(tab):
    tab.tool_buttons[Tool.CROP].click()
    drag(tab.canvas, (0, 0), (100, 50))   # asa NO de la imagen completa, hacia adentro
    assert tab.doc.crop == Rect(100, 50, 700, 450)


def test_arrastrar_el_asa_hasta_el_borde_quita_el_recorte(tab):
    crop_with_tool(tab, (50, 50), (800, 500))
    assert tab.doc.crop == Rect(50, 50, 750, 450)
    drag(tab.canvas, (50, 50), (0, 0))   # asa NO de vuelta a la esquina de la imagen
    assert tab.doc.crop is None
    tab.controller.undo()
    assert tab.doc.crop == Rect(50, 50, 750, 450)


def test_el_asa_no_baja_del_lado_minimo(tab):
    crop_with_tool(tab)
    drag(tab.canvas, (500, 200), (0, 200))   # asa E arrastrada mas alla del lado opuesto
    assert tab.doc.crop.w == 16 and tab.doc.crop.x == 100


def test_esc_cancela_el_recorte_en_curso(tab):
    tab.tool_buttons[Tool.CROP].click()
    press(tab.canvas, (100, 50))
    move(tab.canvas, (400, 300))
    assert tab.controller.crop_draft is not None
    tab.controller.cancel()
    release(tab.canvas, (400, 300))
    assert tab.controller.crop_draft is None and tab.doc.crop is None
    assert tab.controller.stack.count() == 0


def test_el_recorte_ensucia_el_proyecto_y_el_borrador_no(tab):
    assert not tab.is_dirty()
    tab.tool_buttons[Tool.CROP].click()
    press(tab.canvas, (100, 50))
    move(tab.canvas, (400, 300))
    assert not tab.is_dirty()   # solo es un borrador
    release(tab.canvas, (400, 300))
    assert tab.is_dirty()


def test_el_panel_muestra_el_tamano_y_quita_el_recorte(tab):
    crop_with_tool(tab)
    panel = tab.panel
    assert panel._title.text() == "Recortar"
    assert "400 x 300" in panel._crop_size.text()
    assert panel._crop_remove_tool.isEnabled()
    panel._crop_remove_tool.click()
    assert tab.doc.crop is None
    assert not panel._crop_remove_tool.isEnabled()
    assert "Sin recorte" in panel._crop_size.text()


def test_el_panel_avisa_de_las_anotaciones_que_quedan_fuera(tab):
    tab.tool_buttons[Tool.MARKER_PLAIN].click()
    drag(tab.canvas, (10, 400), (100, 460))   # esquina inferior izquierda
    tab.controller.set_crop(Rect(300, 50, 400, 300))
    tab.tool_buttons[Tool.CROP].click()
    assert tab.panel._crop_outside.isVisible() or not tab.panel._crop_outside.isHidden()
    assert "1 anotacion" in tab.panel._crop_outside.text()
    tab.controller.set_crop(None)
    assert tab.panel._crop_outside.isHidden()


def test_la_pagina_del_documento_ofrece_quitar_el_recorte(tab):
    crop_with_tool(tab)
    tab.controller.set_tool(Tool.SELECT)
    assert not tab.panel._crop_remove.isHidden()
    assert "400 x 300" in tab.panel._crop_info.text()
    tab.panel._crop_remove.click()
    assert tab.doc.crop is None and tab.panel._crop_remove.isHidden()


def test_la_barra_de_info_muestra_el_recorte(tab):
    crop_with_tool(tab)
    assert "400 x 300" in tab.info_label.text() and "800 x 500" in tab.info_label.text()


def test_exportar_con_recorte_y_reabrir_el_proyecto(tab, tmp_path):
    crop_with_tool(tab)
    tab.tool_buttons[Tool.STEP].click()
    press(tab.canvas, (200, 150))
    release(tab.canvas, (200, 150))
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    assert Image.open(out).size == (400, 300)
    assert tab.save_project()
    # reabrir la captura recupera el recorte
    tab2 = AnnotateTab()
    tab2.load_capture(tmp_path / "cap.png")
    assert tab2.doc.crop == Rect(100, 50, 400, 300) and len(tab2.doc.items) == 1


def test_la_lupa_nueva_se_coloca_dentro_del_recorte(tab):
    from core.annotate.model import Magnifier

    crop_with_tool(tab)
    tab.controller.set_tool(Tool.SELECT)
    tab.tool_buttons[Tool.LENS].click()
    drag(tab.canvas, (130, 80), (180, 120))
    lens = tab.doc.items[0]
    assert isinstance(lens, Magnifier)
    assert tab.doc.view.x <= lens.lens_center[0] <= tab.doc.view.right
    assert tab.doc.view.y <= lens.lens_center[1] <= tab.doc.view.bottom
