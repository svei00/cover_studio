"""Orden de las capas y menu de clic derecho (fase 2 de Pegar encima)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication

from core.annotate.layers import Order, can_reorder, layer_of, reorder
from core.annotate.model import Arrow, ImageOverlay, Marker, Rect, Redaction, Spotlight
from ui.annotate.canvas import AnnotateCanvas
from ui.annotate.context_menu import ORDER_ACTIONS, build_context_menu
from ui.annotate.controller import Tool
from ui.annotate.panel import _PAGE_IMAGE
from ui.annotate.tab import AnnotateTab


def _m(i):
    return Marker(f"m{i}", Rect(10 * i, 10, 30, 30))


def _o(i):
    return ImageOverlay(f"o{i}", f"x{i}.png", (50, 50), Rect(10 * i, 100, 50, 50))


def _ids(items):
    return [i.id for i in items]


# --- logica pura ------------------------------------------------------------------


def test_cada_tipo_pertenece_a_su_capa():
    assert layer_of(_m(1)) == "annotation" and layer_of(Arrow("a", (0, 0), (5, 5))) == "annotation"
    assert layer_of(_o(1)) == "image"
    assert layer_of(Redaction("r", Rect(0, 0, 5, 5))) is None and layer_of(Spotlight("f", Rect(0, 0, 5, 5))) is None


def test_traer_al_frente_y_enviar_atras():
    items = [_m(1), _m(2), _m(3)]
    assert _ids(reorder(items, {"m1"}, Order.FRONT)) == ["m2", "m3", "m1"]
    assert _ids(reorder(items, {"m3"}, Order.BACK)) == ["m3", "m1", "m2"]


def test_subir_y_bajar_un_nivel():
    items = [_m(1), _m(2), _m(3)]
    assert _ids(reorder(items, {"m1"}, Order.FORWARD)) == ["m2", "m1", "m3"]
    assert _ids(reorder(items, {"m3"}, Order.BACKWARD)) == ["m1", "m3", "m2"]


def test_varias_a_la_vez_conservan_su_orden_relativo():
    items = [_m(1), _m(2), _m(3), _m(4)]
    assert _ids(reorder(items, {"m1", "m3"}, Order.FRONT)) == ["m2", "m4", "m1", "m3"]
    assert _ids(reorder(items, {"m2", "m4"}, Order.BACK)) == ["m2", "m4", "m1", "m3"]
    assert _ids(reorder(items, {"m1", "m2"}, Order.FORWARD)) == ["m3", "m1", "m2", "m4"]      # adyacentes suben juntas
    assert _ids(reorder(items, {"m3", "m4"}, Order.BACKWARD)) == ["m1", "m3", "m4", "m2"]


def test_subir_con_una_en_la_cima_y_otra_debajo_solo_mueve_la_que_puede():
    items = [_m(1), _m(2), _m(3)]
    assert _ids(reorder(items, {"m1", "m3"}, Order.FORWARD)) == ["m2", "m1", "m3"]


def test_sin_cambio_cuando_ya_esta_arriba_abajo_o_es_todo():
    items = [_m(1), _m(2), _m(3)]
    assert _ids(reorder(items, {"m3"}, Order.FRONT)) == _ids(items) and _ids(reorder(items, {"m3"}, Order.FORWARD)) == _ids(items)
    assert _ids(reorder(items, {"m1"}, Order.BACK)) == _ids(items) and _ids(reorder(items, {"m1"}, Order.BACKWARD)) == _ids(items)
    assert _ids(reorder(items, {"m1", "m2", "m3"}, Order.FRONT)) == _ids(items)
    assert _ids(reorder(items, set(), Order.FRONT)) == _ids(items)
    assert _ids(reorder(items, {"zzz"}, Order.FRONT)) == _ids(items)


def test_no_modifica_la_lista_original():
    items = [_m(1), _m(2)]
    reorder(items, {"m1"}, Order.FRONT)
    assert _ids(items) == ["m1", "m2"]


def test_las_imagenes_se_ordenan_entre_ellas_y_vuelven_a_sus_posiciones():
    items = [_m(1), _o(1), _m(2), _o(2)]
    out = reorder(items, {"o1"}, Order.FRONT)
    assert _ids(out) == ["m1", "o2", "m2", "o1"]                 # las anotaciones no se movieron
    assert _ids(reorder(items, {"o2"}, Order.BACK)) == ["m1", "o2", "m2", "o1"]


def test_una_imagen_no_pasa_por_encima_de_las_anotaciones():
    items = [_o(1), _m(1), _m(2)]
    assert _ids(reorder(items, {"o1"}, Order.FRONT)) == _ids(items)            # ya es la unica imagen: nada que hacer
    assert not can_reorder(items, {"o1"}, Order.FRONT)
    assert _ids(reorder(items, {"m2"}, Order.BACK)) == ["o1", "m2", "m1"]      # la imagen sigue en su sitio: nadie la pasa


def test_las_anotaciones_no_se_reordenan_respecto_a_las_imagenes():
    items = [_o(1), _m(1), _o(2), _m(2)]
    out = reorder(items, {"m2"}, Order.BACK)
    assert [i.id for i in out if i.id.startswith("o")] == ["o1", "o2"]
    assert [i.id for i in out if i.id.startswith("m")] == ["m2", "m1"]


def test_pixelado_y_foco_no_tienen_orden_que_cambiar():
    items = [Redaction("r1", Rect(0, 0, 5, 5)), _m(1), Spotlight("f1", Rect(0, 0, 9, 9)), _m(2)]
    assert _ids(reorder(items, {"r1"}, Order.FRONT)) == _ids(items)
    assert _ids(reorder(items, {"f1"}, Order.BACK)) == _ids(items)
    assert _ids(reorder(items, {"m1"}, Order.FRONT)) == ["r1", "m2", "f1", "m1"]   # pixelado y foco conservan su posicion


def test_can_reorder():
    items = [_m(1), _m(2), _m(3)]
    assert can_reorder(items, {"m1"}, Order.FRONT) and not can_reorder(items, {"m3"}, Order.FRONT)
    assert can_reorder(items, {"m3"}, Order.BACK) and not can_reorder(items, {"m1"}, Order.BACK)
    assert can_reorder(items, {"m2"}, Order.FORWARD) and can_reorder(items, {"m2"}, Order.BACKWARD)


# --- controlador y menu -----------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    Image.new("RGB", (100, 80), (220, 30, 30)).save(tmp_path / "rojo.png")
    Image.new("RGB", (100, 80), (30, 30, 220)).save(tmp_path / "azul.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _two_images(tab, tmp_path):
    """Una roja y una azul que se solapan; la azul se agrego despues (queda encima)."""
    tab.controller.add_overlay(tmp_path / "rojo.png", (100, 80))
    red = tab.controller.selected_item()
    tab.controller.add_overlay(tmp_path / "azul.png", (100, 80))
    blue = tab.controller.selected_item()
    tab.controller.select(blue.id)
    tab.controller.nudge(30, 20)
    return red.id, blue.id


def _px(tab, x, y):
    return tab._base_qimage.pixelColor(x, y).name()


def test_enviar_atras_cambia_lo_que_se_ve_en_la_vista_previa_y_se_deshace(tab, tmp_path):
    red, blue = _two_images(tab, tmp_path)
    r = tab.controller.item_by_id(red).rect
    x, y = int(r.x) + 50, int(r.y) + 40                      # dentro de las dos
    assert _px(tab, x, y) == "#1e1edc"                         # la azul esta encima
    tab.controller.select(blue)
    tab.controller.reorder_selected(Order.BACK)
    QApplication.processEvents()
    assert _px(tab, x, y) == "#dc1e1e"
    tab.controller.undo()
    QApplication.processEvents()
    assert _px(tab, x, y) == "#1e1edc"
    tab.controller.redo()
    QApplication.processEvents()
    assert _px(tab, x, y) == "#dc1e1e"


def test_reordenar_es_un_solo_paso_y_si_no_cambia_nada_no_agrega_ninguno(tab, tmp_path):
    red, blue = _two_images(tab, tmp_path)
    steps = tab.controller.stack.count()
    tab.controller.select(blue)
    tab.controller.reorder_selected(Order.FRONT)                 # ya esta arriba
    assert tab.controller.stack.count() == steps
    tab.controller.reorder_selected(Order.BACK)
    assert tab.controller.stack.count() == steps + 1
    assert [i.id for i in tab.doc.items] == [blue, red]
    tab.controller.undo()
    assert [i.id for i in tab.doc.items] == [red, blue]


def test_reordenar_varias_seleccionadas_en_un_paso(tab):
    for i in range(3):
        tab.doc.items.append(_m(i + 1))
    tab.controller.changed.emit()
    tab.controller.select_many(["m1", "m2"])
    steps = tab.controller.stack.count()
    tab.controller.reorder_selected(Order.FRONT)
    assert [i.id for i in tab.doc.items] == ["m3", "m1", "m2"] and tab.controller.stack.count() == steps + 1
    tab.controller.undo()
    assert [i.id for i in tab.doc.items] == ["m1", "m2", "m3"]


def test_select_for_context_menu(tab):
    a, b = _m(5), Marker("mb", Rect(400, 300, 60, 60))
    tab.doc.items.extend([a, b])
    tab.controller.changed.emit()
    c = tab.controller
    assert c.select_for_context_menu((a.rect.x, a.rect.y + 10), 6) and c.selected_id == "m5"
    tab.controller.select_many(["m5", "mb"])
    assert c.select_for_context_menu((b.rect.x, b.rect.y + 10), 6) and set(c.selected_ids) == {"m5", "mb"}   # se conserva
    assert c.select_for_context_menu((a.rect.x, a.rect.y + 10), 6) and set(c.selected_ids) == {"m5", "mb"}
    c.select(None)
    assert not c.select_for_context_menu((700, 450), 6) and c.selected_id is None                              # un hueco
    assert c.select_for_context_menu((b.rect.x, b.rect.y + 10), 6) and c.selected_id == "mb"


def test_el_clic_derecho_no_abre_menu_con_una_herramienta_de_dibujo_ni_en_pleno_gesto(tab):
    a = _m(5)
    tab.doc.items.append(a)
    tab.controller.changed.emit()
    tab.controller.set_tool(Tool.MARKER)
    assert not tab.controller.select_for_context_menu((a.rect.x, a.rect.y + 10), 6)
    tab.controller.set_tool(Tool.SELECT)
    tab.controller._mode = "move"
    assert not tab.controller.select_for_context_menu((a.rect.x, a.rect.y + 10), 6)
    tab.controller._mode = None


def test_menu_sin_seleccion_no_existe(tab):
    assert build_context_menu(tab.controller) is None


_KEEP = []   # el menu se destruye con la ultima referencia y se lleva sus acciones: en la app lo mantiene vivo exec()


def _actions(menu):
    _KEEP.append(menu)
    return {a.data(): a for a in menu.actions() if a.data()}


def test_menu_de_una_anotacion_tiene_orden_y_borrar(tab):
    for i in range(3):
        tab.doc.items.append(_m(i + 1))
    tab.controller.changed.emit()
    tab.controller.select("m2")
    acts = _actions(build_context_menu(tab.controller))
    assert set(acts) == {o.value for o, _ in ORDER_ACTIONS} | {"delete"}
    assert all(acts[o.value].isEnabled() for o, _ in ORDER_ACTIONS) and acts["delete"].text() == "Borrar"
    tab.controller.select("m3")                                       # la de arriba
    acts = _actions(build_context_menu(tab.controller))
    assert not acts["front"].isEnabled() and not acts["forward"].isEnabled() and acts["back"].isEnabled()


def test_menu_de_varias_cuenta_las_que_borra(tab):
    for i in range(3):
        tab.doc.items.append(_m(i + 1))
    tab.controller.changed.emit()
    tab.controller.select_many(["m1", "m2"])
    assert _actions(build_context_menu(tab.controller))["delete"].text() == "Borrar (2)"


def test_menu_de_una_imagen_pegada_agrega_sombra_y_tamano_real(tab, tmp_path):
    tab.controller.add_overlay(tmp_path / "rojo.png", (100, 80))
    acts = _actions(build_context_menu(tab.controller))
    assert {"shadow", "real_size"} <= set(acts)
    assert acts["shadow"].isCheckable() and not acts["shadow"].isChecked() and not acts["real_size"].isEnabled()
    acts["shadow"].trigger()
    assert tab.controller.selected_item().shadow is True
    assert _actions(build_context_menu(tab.controller))["shadow"].isChecked()
    _actions(build_context_menu(tab.controller))["shadow"].trigger()
    assert tab.controller.selected_item().shadow is False


def test_tamano_real_desde_el_menu(tab, tmp_path):
    tab.controller.add_overlay(tmp_path / "rojo.png", (100, 80))
    item = tab.controller.selected_item()
    tab.controller.edit_selected(_merge=False, rect=Rect(item.rect.x, item.rect.y, 200, 160))
    act = _actions(build_context_menu(tab.controller))["real_size"]
    assert act.isEnabled()
    act.trigger()
    assert (tab.controller.selected_item().rect.w, tab.controller.selected_item().rect.h) == (100, 80)


def test_acciones_del_menu_ordenan_y_borran(tab, tmp_path):
    red, blue = _two_images(tab, tmp_path)
    tab.controller.select(blue)
    _actions(build_context_menu(tab.controller))["back"].trigger()
    assert [i.id for i in tab.doc.items] == [blue, red]
    _actions(build_context_menu(tab.controller))["delete"].trigger()
    assert [i.id for i in tab.doc.items] == [red]


# --- el evento de clic derecho en el lienzo ------------------------------------------


@pytest.fixture
def exec_calls(monkeypatch):
    """Los textos de cada menu que el lienzo habria abierto (el real es modal: conftest lo anula y aqui se registra)."""
    calls = []
    monkeypatch.setattr(
        AnnotateCanvas, "_exec_menu", lambda self, menu, pos: calls.append([a.text() for a in menu.actions() if a.text()]))
    return calls


def _right_click(tab, pt):
    pos = tab.canvas.image_to_view(pt).toPoint()
    QApplication.sendEvent(tab.canvas, QContextMenuEvent(QContextMenuEvent.Mouse, pos, tab.canvas.mapToGlobal(pos)))


def test_clic_derecho_sobre_una_imagen_abre_su_menu_y_la_selecciona(tab, tmp_path, exec_calls):
    tab.controller.add_overlay(tmp_path / "rojo.png", (100, 80))
    item = tab.controller.selected_item()
    tab.controller.select(None)
    _right_click(tab, item.rect.center)
    assert tab.controller.selected_id == item.id
    assert len(exec_calls) == 1 and "Sombra flotante" in exec_calls[0] and "Traer al frente" in exec_calls[0]


def test_clic_derecho_en_un_hueco_no_abre_menu(tab, exec_calls):
    _right_click(tab, (50, 50))
    assert exec_calls == []


def test_clic_derecho_no_cambia_nada_en_el_documento(tab, tmp_path, exec_calls):
    tab.controller.add_overlay(tmp_path / "rojo.png", (100, 80))
    item = tab.controller.selected_item()
    steps = tab.controller.stack.count()
    _right_click(tab, item.rect.center)
    assert tab.controller.stack.count() == steps and tab.controller.item_by_id(item.id) == item


# --- panel -------------------------------------------------------------------------


def test_botones_al_frente_y_atras_de_la_pagina_de_la_imagen(tab, tmp_path):
    red, blue = _two_images(tab, tmp_path)
    tab.controller.select(blue)
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_IMAGE
    assert not p._img_front.isEnabled() and p._img_back.isEnabled()
    p._img_back.click()
    assert [i.id for i in tab.doc.items] == [blue, red]
    assert p._img_front.isEnabled() and not p._img_back.isEnabled()
    p._img_front.click()
    assert [i.id for i in tab.doc.items] == [red, blue]
