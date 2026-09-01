import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.annotate import edit, lens
from core.annotate.model import AnnotationDoc, LensShape, Magnifier, Rect
from ui.annotate.controller import EditController, Tool
from ui.annotate.tab import AnnotateTab

TOL = 6.0
M = Magnifier("l1", Rect(100, 100, 60, 40), (400.0, 300.0), 2.0, LensShape.CIRCLE)  # origen cuadrado 60, lente r=60


# --- operaciones puras de edicion ------------------------------------------

def test_hit_lens_part_cuerpo_borde_y_nada():
    assert edit.hit_lens_part(M, (400.0, 300.0), TOL) == "lens"
    assert edit.hit_lens_part(M, (130.0 + 30, 120.0), TOL) == "source"   # borde del origen circular
    assert edit.hit_lens_part(M, (130.0, 120.0), TOL) is None             # el interior del origen queda libre
    assert edit.hit_lens_part(M, (800.0, 600.0), TOL) is None


def test_el_cuerpo_del_lente_gana_si_se_solapan():
    encima = Magnifier("l", Rect(100, 100, 60, 40), (130.0, 120.0), 2.0)
    assert edit.hit_lens_part(encima, (130.0 + 30, 120.0), TOL) == "lens"


def test_hit_test_encuentra_la_lupa_por_cualquiera_de_sus_partes():
    assert edit.hit_test([M], (400.0, 300.0), TOL, 1.0) == "l1"
    assert edit.hit_test([M], (160.0, 120.0), TOL, 1.0) == "l1"
    assert edit.hit_test([M], (700.0, 500.0), TOL, 1.0) is None


def test_la_lupa_tiene_nueve_asas_y_la_del_lente_esta_en_su_esquina():
    handles = edit.item_handles(M)
    assert len(handles) == 9
    box = lens.lens_rect(M)
    assert handles[edit.Handle.LENS] == (box.right, box.bottom)
    assert handles[edit.Handle.NW] == (lens.effective_source(M).x, lens.effective_source(M).y)


def test_move_item_de_la_lupa_segun_la_parte():
    solo_lente = edit.move_item(M, 10.0, 5.0, "lens")
    assert solo_lente.lens_center == (410.0, 305.0) and solo_lente.source == M.source
    solo_origen = edit.move_item(M, 10.0, 5.0, "source")
    assert solo_origen.source == Rect(110, 105, 60, 40) and solo_origen.lens_center == M.lens_center
    ambos = edit.move_item(M, 10.0, 5.0)
    assert ambos.source.x == 110 and ambos.lens_center == (410.0, 305.0)


def test_el_asa_del_lente_cambia_el_zoom_y_ancla_su_esquina_superior_izquierda():
    box = lens.lens_rect(M)  # (340, 240) 120x120
    mas = edit.resize_item(M, edit.Handle.LENS, (box.x + 180.0, box.y + 180.0))
    assert mas.zoom == pytest.approx(3.0)
    nuevo = lens.lens_rect(mas)
    assert (nuevo.x, nuevo.y) == pytest.approx((box.x, box.y)) and nuevo.w == pytest.approx(180)


def test_el_zoom_se_acota_entre_los_limites():
    box = lens.lens_rect(M)
    assert edit.resize_item(M, edit.Handle.LENS, (box.x + 1.0, box.y + 1.0)).zoom == lens.MIN_ZOOM
    assert edit.resize_item(M, edit.Handle.LENS, (box.x + 9999.0, box.y + 9999.0)).zoom == lens.MAX_ZOOM


def test_las_asas_del_origen_redimensionan_la_zona_ampliada():
    nuevo = edit.resize_item(M, edit.Handle.E, (200.0, 120.0))
    assert lens.effective_source(nuevo).right == pytest.approx(200.0)
    assert nuevo.lens_center == M.lens_center and nuevo.zoom == M.zoom


def test_selection_rects_de_la_lupa_son_origen_y_lente():
    assert edit.selection_rects(M, 1.0) == [lens.effective_source(M), lens.lens_rect(M)]


# --- controlador -----------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (1000, 700)))
    return c


def drag(c, a, b):
    c.press(a, TOL)
    c.move(b)
    c.release(b)


def test_crear_una_lupa_arrastrando_coloca_el_lente_sin_cubrir_el_origen(ctl):
    ctl.set_tool(Tool.LENS)
    drag(ctl, (100.0, 100.0), (180.0, 150.0))
    item = ctl.doc.items[0]
    assert isinstance(item, Magnifier) and item.zoom == 2.0 and item.shape is LensShape.CIRCLE
    assert not lens.lens_rect(item).intersects(lens.effective_source(item))
    box = lens.lens_rect(item)
    assert box.x >= 0 and box.y >= 0 and box.right <= 1000 and box.bottom <= 700
    assert ctl.selected_id == item.id and ctl.tool is Tool.SELECT
    ctl.undo()
    assert ctl.doc.items == []


def test_una_lupa_con_origen_diminuto_se_descarta(ctl):
    ctl.set_tool(Tool.LENS)
    drag(ctl, (100.0, 100.0), (106.0, 106.0))
    assert ctl.doc.items == [] and not ctl.stack.canUndo()


def test_la_lupa_nueva_esquiva_las_otras_anotaciones(ctl):
    ctl.set_tool(Tool.LENS)
    drag(ctl, (100.0, 300.0), (160.0, 340.0))
    primero = lens.lens_rect(ctl.doc.items[0])
    ctl.set_tool(Tool.LENS)
    drag(ctl, (100.0, 380.0), (160.0, 420.0))
    segundo = lens.lens_rect(ctl.doc.items[1])
    assert not primero.intersects(segundo)


def _con_lupa(ctl):
    ctl.doc.items.append(M)
    ctl.changed.emit()


def test_arrastrar_el_cuerpo_del_lente_solo_mueve_el_lente(ctl):
    _con_lupa(ctl)
    drag(ctl, (400.0, 300.0), (450.0, 340.0))
    item = ctl.doc.items[0]
    assert item.lens_center == (450.0, 340.0) and item.source == M.source
    ctl.undo()
    assert ctl.doc.items[0] == M


def test_arrastrar_el_borde_del_origen_solo_mueve_el_origen(ctl):
    _con_lupa(ctl)
    drag(ctl, (160.0, 120.0), (200.0, 150.0))
    item = ctl.doc.items[0]
    assert item.source == Rect(140, 130, 60, 40) and item.lens_center == M.lens_center


def test_arrastrar_el_asa_del_lente_cambia_el_zoom(ctl):
    _con_lupa(ctl)
    ctl.select("l1")
    box = lens.lens_rect(M)
    drag(ctl, (box.right, box.bottom), (box.x + 240.0, box.y + 240.0))
    assert ctl.doc.items[0].zoom == pytest.approx(4.0)
    ctl.undo()
    assert ctl.doc.items[0].zoom == 2.0


def test_recolocar_saca_el_lente_de_encima_del_origen(ctl):
    tapado = Magnifier("l1", Rect(100, 100, 60, 40), (130.0, 120.0), 2.0, LensShape.CIRCLE)
    ctl.doc.items.append(tapado)
    ctl.select("l1")
    ctl.auto_place_selected_lens()
    item = ctl.doc.items[0]
    assert not lens.lens_rect(item).intersects(lens.effective_source(item))
    ctl.undo()
    assert ctl.doc.items[0].lens_center == (130.0, 120.0)


def test_editar_zoom_y_forma_desde_propiedades(ctl):
    _con_lupa(ctl)
    ctl.select("l1")
    ctl.edit_selected(zoom=3.5)
    ctl.edit_selected(shape=LensShape.ROUNDED)
    item = ctl.doc.items[0]
    assert item.zoom == 3.5 and item.shape is LensShape.ROUNDED
    ctl.undo()  # forma y zoom son decisiones distintas: dos pasos, no uno
    assert ctl.doc.items[0].shape is LensShape.CIRCLE and ctl.doc.items[0].zoom == 3.5
    ctl.undo()
    assert ctl.doc.items[0] == M


def test_cambiar_zoom_o_forma_recoloca_el_lente_si_quedaria_encima_del_origen(ctl):
    pegado = Magnifier("l1", Rect(100, 100, 60, 40), (240.0, 120.0), 1.0, LensShape.ROUNDED)  # justo a la derecha
    ctl.doc.items.append(pegado)
    ctl.select("l1")
    ctl.edit_selected(zoom=3.0)  # el lente crece y se montaria sobre el origen
    item = ctl.doc.items[0]
    assert item.zoom == 3.0
    assert not lens.lens_rect(item).intersects(lens.effective_source(item))


def test_cambiar_forma_y_zoom_tras_crear_deja_el_lente_con_hueco_visible(ctl):
    ctl.set_tool(Tool.LENS)
    drag(ctl, (330.0, 500.0), (420.0, 528.0))
    ctl.edit_selected(shape=LensShape.ROUNDED)
    ctl.edit_selected(zoom=2.5)
    item = ctl.doc.items[0]
    assert not lens.is_crowded(item)
    assert lens.connector_segments(item)  # hay hueco suficiente para que se dibuje el conector


def test_cambiar_zoom_no_mueve_el_lente_si_no_hay_solapamiento(ctl):
    lejos = Magnifier("l1", Rect(100, 100, 60, 40), (700.0, 500.0), 1.0, LensShape.ROUNDED)
    ctl.doc.items.append(lejos)
    ctl.select("l1")
    ctl.edit_selected(zoom=2.0)
    assert ctl.doc.items[0].lens_center == (700.0, 500.0)


# --- interfaz completa -----------------------------------------------------

def _capture(path: Path, size=(800, 500)) -> Path:
    img = Image.new("RGB", size, (40, 60, 90))
    img.paste((0, 200, 0), (100, 100, 180, 160))  # cuadro verde que se va a ampliar
    img.save(path)
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


def _mouse(canvas, kind, pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def mdrag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton)


def test_dibujar_una_lupa_con_el_mouse_muestra_su_panel(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    item = tab.doc.items[0]
    assert isinstance(item, Magnifier)
    assert tab.panel._pages.currentIndex() == 6 and tab.panel._title.text() == "Lupa"
    assert tab.panel._lens_zoom.value() == 2.0 and not tab.panel._lens_warning.isVisible()


def test_el_lente_pintado_en_pantalla_muestra_la_zona_ampliada(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    item = tab.doc.items[0]
    assert item.id in tab._lens_cache
    img = tab.canvas.grab().toImage()
    center = tab.canvas.image_to_view(lens.lens_rect(item).center)
    px = QColor(img.pixel(int(center.x()), int(center.y())))
    assert (px.red(), px.green(), px.blue()) == pytest.approx((0, 200, 0), abs=8)


def test_zoom_alto_muestra_la_advertencia_y_cambia_el_tamano_del_lente(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    antes = lens.lens_rect(tab.doc.items[0]).w
    tab.panel._lens_zoom.setValue(4.0)
    assert tab.doc.items[0].zoom == 4.0 and lens.lens_rect(tab.doc.items[0]).w == pytest.approx(antes * 2)
    assert not tab.panel._lens_warning.isHidden()
    tab.panel._lens_zoom.setValue(2.0)
    assert tab.panel._lens_warning.isHidden()


def test_forma_y_conector_desde_el_panel(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    combo = tab.panel._lens_shape
    combo.setCurrentIndex(combo.findData(LensShape.ROUNDED.value))
    assert tab.doc.items[0].shape is LensShape.ROUNDED
    tab.panel._lens_connector.setChecked(False)
    assert tab.doc.items[0].connector is False


def test_mover_el_lente_no_recalcula_el_recorte_pero_cambiar_el_zoom_si(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    item = tab.doc.items[0]
    recorte = tab._lens_cache[item.id][1]
    QTest.keyClick(tab.canvas, Qt.Key_Right)  # empuja ambos (origen y lente)
    assert tab._lens_cache[item.id][1] is not recorte  # el origen se movio -> otro recorte
    recorte = tab._lens_cache[item.id][1]
    tab.controller.edit_selected(lens_center=(tab.doc.items[0].lens_center[0] + 5, tab.doc.items[0].lens_center[1]))
    assert tab._lens_cache[item.id][1] is recorte  # solo se movio el lente
    tab.panel._lens_zoom.setValue(3.0)
    assert tab._lens_cache[item.id][1] is not recorte


def test_borrar_la_lupa_limpia_su_recorte(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    tab.delete_btn.click()
    assert tab._lens_cache == {}


def test_un_pixelado_se_respeta_dentro_de_la_lupa(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    item = tab.doc.items[0]
    antes = tab._lens_cache[item.id][1]
    tab.tool_buttons[Tool.REDACT].click()
    mdrag(tab.canvas, (90.0, 90.0), (190.0, 170.0))  # cubre todo el origen
    assert tab._lens_cache[item.id][1] is not antes  # se recalculo desde el bitmap pixelado


def test_la_lupa_se_exporta_y_se_puede_reabrir(tab, tmp_path):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (180.0, 160.0))
    item = tab.doc.items[0]
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    result = Image.open(out).convert("RGB")
    cx, cy = (round(v) for v in lens.lens_rect(item).center)
    assert result.getpixel((cx, cy)) == pytest.approx((0, 200, 0), abs=8)
    tab.load_capture(tmp_path / "cap.png")
    assert tab.doc.items == [item]
