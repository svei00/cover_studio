"""Seleccion multiple: Ctrl / Shift + clic, rectangulo de seleccion, Ctrl + A, mover / borrar / empujar un grupo (cada
accion es UN paso de deshacer) y la pagina del panel."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent, QShortcut
from PySide6.QtWidgets import QApplication

from core.annotate.model import AnnotationDoc, Icon, IconKind, Magnifier, Marker, Rect, Spotlight, StepBadge
from ui.annotate.controller import EditController, Tool
from ui.annotate.panel import _PAGE_ICON, _PAGE_MULTI
from ui.annotate.tab import AnnotateTab

TOL = 6.0


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _icons():
    """Cuatro iconos en columna (un poco desalineados, como los pondria alguien a ojo) y uno aparte."""
    return [
        Icon("a1", (100.0, 100.0), IconKind.CHECK),
        Icon("a2", (104.0, 200.0), IconKind.CHECK),
        Icon("a3", (97.0, 300.0), IconKind.CROSS),
        Icon("a4", (101.0, 400.0), IconKind.CROSS),
        Icon("a5", (600.0, 250.0), IconKind.STAR),
    ]


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (1000, 700), _icons(), style_scale=1.0))
    return c


def _centers(c):
    return {i.id: i.center for i in c.doc.items}


# --- seleccion -------------------------------------------------------------------------------------------

def test_varias_seleccionadas_la_principal_es_la_ultima_y_no_hay_una_sola_para_editar(ctl):
    ctl.select_many(["a1", "a3"])
    assert ctl.selected_ids == ("a1", "a3") and ctl.selected_id == "a3"
    assert ctl.selected_item() is None                                  # con varias no se editan propiedades
    assert [i.id for i in ctl.selected_items()] == ["a1", "a3"]
    ctl.select("a2")
    assert ctl.selected_ids == ("a2",) and ctl.selected_item().id == "a2"
    ctl.select(None)
    assert ctl.selected_ids == () and ctl.selected_id is None


def test_select_many_no_repite_y_avisa_solo_si_cambia(ctl):
    avisos = []
    ctl.selectionChanged.connect(lambda: avisos.append(1))
    ctl.select_many(["a1", "a1", "a2"])
    ctl.select_many(["a1", "a2"])
    assert ctl.selected_ids == ("a1", "a2") and len(avisos) == 1


def test_ctrl_clic_suma_y_quita_sin_arrastrar(ctl):
    ctl.press((100.0, 100.0), TOL)
    ctl.release((100.0, 100.0))
    ctl.press((104.0, 200.0), TOL, additive=True)
    ctl.move((300.0, 300.0))                                            # no hay arrastre: era solo sumar
    ctl.release((300.0, 300.0))
    assert ctl.selected_ids == ("a1", "a2") and _centers(ctl)["a2"] == (104.0, 200.0)
    ctl.press((104.0, 200.0), TOL, additive=True)
    ctl.release((104.0, 200.0))
    assert ctl.selected_ids == ("a1",)
    assert not ctl.stack.canUndo()                                      # seleccionar no ensucia el historial


def test_clic_sin_ctrl_sobre_una_no_seleccionada_reemplaza_la_seleccion(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.press((97.0, 300.0), TOL)
    ctl.release((97.0, 300.0))
    assert ctl.selected_ids == ("a3",)


def test_ctrl_a_selecciona_todo_y_vuelve_a_seleccionar(ctl):
    ctl.set_tool(Tool.MARKER)
    ctl.select_all()
    assert ctl.tool is Tool.SELECT and ctl.selected_ids == ("a1", "a2", "a3", "a4", "a5")


def test_esc_deselecciona_todo(ctl):
    ctl.select_all()
    ctl.cancel()
    assert ctl.selected_ids == ()


# --- rectangulo de seleccion -----------------------------------------------------------------------------

def test_arrastrar_sobre_un_hueco_selecciona_lo_que_toca_y_el_rectangulo_se_quita_al_soltar(ctl):
    ctl.press((50.0, 60.0), TOL)
    assert ctl.marquee is None
    ctl.move((160.0, 250.0))
    assert ctl.marquee == Rect(50.0, 60.0, 110.0, 190.0)
    assert ctl.selected_ids == ("a1", "a2")                             # en vivo, mientras se arrastra
    ctl.move((160.0, 450.0))
    assert ctl.selected_ids == ("a1", "a2", "a3", "a4")
    ctl.release((160.0, 450.0))
    assert ctl.marquee is None and ctl.selected_ids == ("a1", "a2", "a3", "a4") and not ctl.stack.canUndo()


def test_el_rectangulo_se_puede_dibujar_en_cualquier_direccion(ctl):
    ctl.press((700.0, 500.0), TOL)
    ctl.move((560.0, 220.0))
    ctl.release((560.0, 220.0))
    assert ctl.selected_ids == ("a5",)


def test_un_clic_en_un_hueco_deselecciona_y_un_temblor_tambien(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.press((800.0, 650.0), TOL)
    ctl.move((801.0, 651.0))
    ctl.release((801.0, 651.0))
    assert ctl.selected_ids == () and ctl.marquee is None


def test_con_ctrl_el_rectangulo_suma_a_lo_ya_seleccionado(ctl):
    ctl.select("a5")
    ctl.press((50.0, 60.0), TOL, additive=True)
    ctl.move((160.0, 250.0))
    ctl.release((160.0, 250.0))
    assert ctl.selected_ids == ("a5", "a1", "a2")


def test_un_clic_con_ctrl_en_un_hueco_conserva_la_seleccion(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.press((800.0, 650.0), TOL, additive=True)
    ctl.release((800.0, 650.0))
    assert ctl.selected_ids == ("a1", "a2")


def test_el_rectangulo_toca_el_origen_o_el_lente_de_una_lupa_y_el_foco_solo_si_lo_contiene(ctl):
    lupa = Magnifier("m", Rect(700.0, 500.0, 60.0, 40.0), (850.0, 600.0), 2.0)
    foco = Spotlight("f", Rect(0.0, 0.0, 1000.0, 700.0))
    ctl.doc.items.extend([lupa, foco])
    assert "m" in ctl.items_in_rect(Rect(690.0, 490.0, 40.0, 30.0))      # solo toca el origen
    assert "m" in ctl.items_in_rect(Rect(840.0, 590.0, 5.0, 5.0))        # solo toca el lente
    assert "f" not in ctl.items_in_rect(Rect(50.0, 60.0, 110.0, 190.0))  # el foco abarca toda la captura
    assert "f" in ctl.items_in_rect(Rect(-5.0, -5.0, 1100.0, 800.0))


# --- mover en grupo --------------------------------------------------------------------------------------

def test_arrastrar_una_de_varias_seleccionadas_las_mueve_todas_en_un_solo_paso(ctl):
    ctl.select_many(["a1", "a2", "a3"])
    ctl.press((104.0, 200.0), TOL)
    assert ctl.selected_ids == ("a1", "a2", "a3")                       # no se reduce a una
    ctl.move((144.0, 215.0))
    assert _centers(ctl)["a1"] == (140.0, 115.0) and _centers(ctl)["a3"] == (137.0, 315.0)   # en vivo
    ctl.release((144.0, 215.0))
    c = _centers(ctl)
    assert c["a1"] == (140.0, 115.0) and c["a2"] == (144.0, 215.0) and c["a3"] == (137.0, 315.0)
    assert c["a4"] == (101.0, 400.0) and c["a5"] == (600.0, 250.0)       # las demas no
    assert ctl.stack.count() == 1
    ctl.undo()
    assert _centers(ctl) == {i.id: i.center for i in _icons()}
    ctl.redo()
    assert _centers(ctl)["a1"] == (140.0, 115.0)


def test_esc_a_mitad_de_un_arrastre_de_grupo_lo_devuelve_todo_a_su_lugar(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.press((100.0, 100.0), TOL)
    ctl.move((180.0, 160.0))
    ctl.cancel()
    ctl.release((180.0, 160.0))
    assert _centers(ctl) == {i.id: i.center for i in _icons()} and not ctl.stack.canUndo()


def test_arrastrar_sin_mover_no_crea_un_paso(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.press((100.0, 100.0), TOL)
    ctl.release((100.0, 100.0))
    assert not ctl.stack.canUndo()


def test_el_grupo_mueve_marcadores_con_su_flecha_a_mano(ctl):
    m = Marker("m", Rect(300.0, 500.0, 100.0, 50.0), arrow_start=(300.0, 600.0), arrow_tip=(350.0, 560.0))
    ctl.doc.items.append(m)
    ctl.select_many(["a5", "m"])
    ctl.press((600.0, 250.0), TOL)
    ctl.move((620.0, 270.0))
    ctl.release((620.0, 270.0))
    moved = ctl.item_by_id("m")
    assert moved.rect == Rect(320.0, 520.0, 100.0, 50.0) and moved.arrow_tip == (370.0, 580.0)


# --- borrar y flechas ------------------------------------------------------------------------------------

def test_borrar_varias_es_un_paso_y_al_deshacer_cada_una_vuelve_a_su_lugar(ctl):
    antes = [i.id for i in ctl.doc.items]
    ctl.select_many(["a2", "a4", "a1"])
    ctl.delete_selected()
    assert [i.id for i in ctl.doc.items] == ["a3", "a5"] and ctl.selected_ids == ()
    assert ctl.stack.count() == 1 and ctl.stack.undoText() == "Borrar"   # un macro = un paso
    ctl.undo()
    assert [i.id for i in ctl.doc.items] == antes                       # un solo deshacer las trae todas, en su orden


def test_borrar_una_sola_sigue_igual(ctl):
    ctl.select("a3")
    ctl.delete_selected()
    assert [i.id for i in ctl.doc.items] == ["a1", "a2", "a4", "a5"] and ctl.stack.count() == 1


def test_las_flechas_del_teclado_empujan_a_todas_y_los_pasos_seguidos_se_fusionan(ctl):
    ctl.select_many(["a1", "a3"])
    ctl.nudge(1.0, 0.0)
    ctl.nudge(1.0, 0.0)
    ctl.nudge(0.0, 10.0)
    c = _centers(ctl)
    assert c["a1"] == (102.0, 110.0) and c["a3"] == (99.0, 310.0) and c["a2"] == (104.0, 200.0)
    assert ctl.stack.count() == 1                                       # una racha de flechas = un deshacer
    ctl.undo()
    assert _centers(ctl) == {i.id: i.center for i in _icons()}


def test_con_una_sola_seleccionada_las_flechas_siguen_funcionando_como_antes(ctl):
    ctl.select("a1")
    ctl.nudge(5.0, 0.0)
    ctl.nudge(5.0, 0.0)
    assert _centers(ctl)["a1"] == (110.0, 100.0) and ctl.stack.count() == 1


def test_editar_propiedades_con_varias_seleccionadas_no_hace_nada(ctl):
    ctl.select_many(["a1", "a2"])
    ctl.edit_selected(size=33.0)
    assert not ctl.stack.canUndo() and ctl.item_by_id("a1").size != 33.0


def test_si_se_borra_una_de_las_seleccionadas_por_deshacer_la_seleccion_se_ajusta(ctl):
    ctl.set_tool(Tool.ICON)
    ctl.press((300.0, 300.0), TOL)                                      # coloca un icono nuevo (a6)
    ctl.release((300.0, 300.0))
    ctl.set_tool(Tool.SELECT)
    ctl.select_many(["a1", "a6"])
    ctl.undo()                                                          # el icono nuevo desaparece
    assert ctl.selected_ids == ("a1",)


# --- interfaz --------------------------------------------------------------------------------------------

@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1400, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    t.doc.items.extend([Icon("a1", (100.0, 100.0)), Icon("a2", (104.0, 200.0)), Icon("a3", (300.0, 150.0), IconKind.CROSS)])
    t.refresh()
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton, mods=Qt.NoModifier):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, mods))


def test_ctrl_clic_y_shift_clic_en_el_lienzo_suman_a_la_seleccion(tab):
    c = tab.canvas
    _mouse(c, QEvent.MouseButtonPress, (100.0, 100.0))
    _mouse(c, QEvent.MouseButtonRelease, (100.0, 100.0), buttons=Qt.NoButton)
    _mouse(c, QEvent.MouseButtonPress, (104.0, 200.0), mods=Qt.ControlModifier)
    _mouse(c, QEvent.MouseButtonRelease, (104.0, 200.0), buttons=Qt.NoButton, mods=Qt.ControlModifier)
    _mouse(c, QEvent.MouseButtonPress, (300.0, 150.0), mods=Qt.ShiftModifier)
    _mouse(c, QEvent.MouseButtonRelease, (300.0, 150.0), buttons=Qt.NoButton, mods=Qt.ShiftModifier)
    assert tab.controller.selected_ids == ("a1", "a2", "a3")


def test_el_panel_muestra_la_pagina_de_seleccion_multiple_con_el_conteo_y_vuelve_a_la_normal(tab):
    p = tab.panel
    tab.controller.select_many(["a1", "a2"])
    QApplication.processEvents()
    assert p._pages.currentIndex() == _PAGE_MULTI and "2 anotaciones" in p._multi_count.text()
    tab.controller.select_many(["a1", "a2", "a3"])
    assert "3 anotaciones" in p._multi_count.text()
    tab.controller.select("a1")
    QApplication.processEvents()
    assert p._pages.currentIndex() == _PAGE_ICON


def test_el_boton_borrar_se_activa_con_una_o_varias_y_borra_todas(tab):
    assert not tab.delete_btn.isEnabled()
    tab.controller.select_many(["a1", "a2"])
    assert tab.delete_btn.isEnabled()
    tab.delete_btn.click()
    assert [i.id for i in tab.doc.items] == ["a3"]


def test_ctrl_a_es_un_atajo_de_la_pestana(qapp):
    keys = {s.key().toString() for s in AnnotateTab().findChildren(QShortcut)}
    assert "Ctrl+A" in keys


def test_el_lienzo_pinta_la_seleccion_multiple_y_el_rectangulo_sin_errores(tab):
    tab.controller.select_many(["a1", "a2", "a3"])
    tab.controller._set_marquee(Rect(50.0, 50.0, 200.0, 120.0))
    assert not tab.canvas.grab().isNull()
    tab.controller._set_marquee(None)


def test_dibujar_un_rectangulo_en_el_lienzo_con_el_mouse_selecciona(tab):
    c = tab.canvas
    _mouse(c, QEvent.MouseButtonPress, (60.0, 60.0))
    _mouse(c, QEvent.MouseMove, (150.0, 250.0), buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(c, QEvent.MouseButtonRelease, (150.0, 250.0), buttons=Qt.NoButton)
    assert tab.controller.selected_ids == ("a1", "a2") and tab.controller.marquee is None
