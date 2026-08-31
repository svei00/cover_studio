import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.annotate.model import AnnotationDoc, Arrow, Marker, Rect, Redaction, StepBadge, TextLabel
from ui.annotate.controller import EditController, Tool

TOL = 6.0


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (800, 600)))
    return c


def drag(c, a, b, tol=TOL):
    c.press(a, tol)
    c.move(b)
    c.release(b)


def test_crear_marcador_arrastrando_lo_selecciona_y_vuelve_a_seleccionar(ctl):
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (100.0, 100.0), (200.0, 160.0))
    assert ctl.doc.items == [Marker("a1", Rect(100, 100, 100, 60))]
    assert ctl.selected_id == "a1" and ctl.tool is Tool.SELECT


def test_crear_arrastrando_hacia_arriba_y_la_izquierda_normaliza_el_rect(ctl):
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (200.0, 160.0), (100.0, 100.0))
    assert ctl.doc.items[0].rect == Rect(100, 100, 100, 60)


def test_deshacer_y_rehacer_la_creacion(ctl):
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (100.0, 100.0), (200.0, 160.0))
    ctl.undo()
    assert ctl.doc.items == [] and ctl.selected_id is None
    ctl.redo()
    assert len(ctl.doc.items) == 1


def test_un_clic_sin_arrastrar_no_crea_nada_ni_ensucia_el_historial(ctl):
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (100.0, 100.0), (101.0, 101.0))
    assert ctl.doc.items == [] and not ctl.stack.canUndo()


def test_crear_flecha_y_descartar_una_demasiado_corta(ctl):
    ctl.set_tool(Tool.ARROW)
    drag(ctl, (10.0, 10.0), (200.0, 10.0))
    assert ctl.doc.items == [Arrow("a1", (10.0, 10.0), (200.0, 10.0))]
    ctl.set_tool(Tool.ARROW)
    drag(ctl, (300.0, 300.0), (303.0, 301.0))
    assert len(ctl.doc.items) == 1


def test_crear_pixelado_usa_bloque_por_defecto(ctl):
    ctl.set_tool(Tool.REDACT)
    drag(ctl, (50.0, 50.0), (150.0, 90.0))
    item = ctl.doc.items[0]
    assert isinstance(item, Redaction) and item.block >= 6 and item.rect == Rect(50, 50, 100, 40)


def test_pasos_continuan_la_numeracion(ctl):
    for x in (100.0, 200.0, 300.0):
        ctl.set_tool(Tool.STEP)
        ctl.press((x, 50.0), TOL)
        ctl.release((x, 50.0))
    assert [i.number for i in ctl.doc.items] == [1, 2, 3]
    assert all(isinstance(i, StepBadge) for i in ctl.doc.items)
    assert ctl.tool is Tool.SELECT


def test_texto_crea_etiqueta_y_pide_editar_el_texto(ctl):
    pedidos = []
    ctl.textEditRequested.connect(lambda: pedidos.append(1))
    ctl.set_tool(Tool.TEXT)
    ctl.press((120.0, 80.0), TOL)
    ctl.release((120.0, 80.0))
    item = ctl.doc.items[0]
    assert isinstance(item, TextLabel) and item.text == "Texto" and item.pos == (120.0, 80.0)
    assert pedidos == [1] and ctl.selected_id == item.id


def test_los_puntos_fuera_de_la_imagen_se_recortan(ctl):
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (-50.0, -50.0), (5000.0, 5000.0))
    assert ctl.doc.items[0].rect == Rect(0, 0, 800, 600)


# --- mover / redimensionar -------------------------------------------------

def _con_marcador(ctl):
    ctl.doc.items.append(Marker("a1", Rect(100, 100, 200, 100)))
    ctl.changed.emit()


def test_mover_arrastrando_el_borde_y_deshacer(ctl):
    _con_marcador(ctl)
    drag(ctl, (100.0, 150.0), (130.0, 170.0))  # agarra el borde izquierdo
    assert ctl.doc.items[0].rect == Rect(130, 120, 200, 100)
    assert ctl.stack.count() == 1
    ctl.undo()
    assert ctl.doc.items[0].rect == Rect(100, 100, 200, 100)
    ctl.redo()
    assert ctl.doc.items[0].rect == Rect(130, 120, 200, 100)


def test_clic_sobre_la_anotacion_sin_mover_no_agrega_historial(ctl):
    _con_marcador(ctl)
    drag(ctl, (100.0, 150.0), (100.0, 150.0))
    assert ctl.selected_id == "a1" and not ctl.stack.canUndo()


def test_clic_en_vacio_deselecciona(ctl):
    _con_marcador(ctl)
    ctl.select("a1")
    drag(ctl, (700.0, 500.0), (700.0, 500.0))
    assert ctl.selected_id is None


def test_redimensionar_con_un_asa_solo_si_esta_seleccionada(ctl):
    _con_marcador(ctl)
    # sin seleccion: el clic en la esquina SE selecciona (esta en el borde), no redimensiona
    drag(ctl, (300.0, 200.0), (300.0, 200.0))
    assert ctl.selected_id == "a1"
    drag(ctl, (300.0, 200.0), (360.0, 240.0))  # ahora si hay asa SE
    assert ctl.doc.items[0].rect == Rect(100, 100, 260, 140)
    ctl.undo()
    assert ctl.doc.items[0].rect == Rect(100, 100, 200, 100)


def test_esc_durante_un_movimiento_restaura_la_anotacion(ctl):
    _con_marcador(ctl)
    ctl.press((100.0, 150.0), TOL)
    ctl.move((160.0, 190.0))
    assert ctl.doc.items[0].rect.x == 160
    ctl.cancel()
    assert ctl.doc.items[0].rect == Rect(100, 100, 200, 100) and not ctl.stack.canUndo()


def test_esc_durante_una_creacion_descarta_el_borrador(ctl):
    ctl.set_tool(Tool.MARKER)
    ctl.press((100.0, 100.0), TOL)
    ctl.move((200.0, 200.0))
    ctl.cancel()
    assert ctl.doc.items == [] and ctl.tool is Tool.SELECT and ctl.selected_id is None


def test_esc_sin_gesto_vuelve_a_seleccionar_y_luego_deselecciona(ctl):
    _con_marcador(ctl)
    ctl.select("a1")
    ctl.set_tool(Tool.ARROW)
    assert ctl.selected_id is None  # elegir una herramienta de creacion deselecciona
    ctl.cancel()
    assert ctl.tool is Tool.SELECT
    ctl.select("a1")
    ctl.cancel()
    assert ctl.selected_id is None


# --- borrar / editar / empujar ---------------------------------------------

def test_borrar_y_deshacer_restituye_la_posicion_en_el_orden(ctl):
    ctl.doc.items.extend([Marker("a1", Rect(0, 0, 10, 10)), Marker("a2", Rect(20, 0, 10, 10)), Marker("a3", Rect(40, 0, 10, 10))])
    ctl.select("a2")
    ctl.delete_selected()
    assert [i.id for i in ctl.doc.items] == ["a1", "a3"] and ctl.selected_id is None
    ctl.undo()
    assert [i.id for i in ctl.doc.items] == ["a1", "a2", "a3"]


def test_borrar_sin_seleccion_no_hace_nada(ctl):
    _con_marcador(ctl)
    ctl.delete_selected()
    assert len(ctl.doc.items) == 1 and not ctl.stack.canUndo()


def test_editar_propiedades_fusiona_los_cambios_seguidos_en_un_paso(ctl):
    ctl.doc.items.append(TextLabel("a1", (10.0, 10.0), "Texto"))
    ctl.select("a1")
    for texto in ("H", "Ho", "Hol", "Hola"):
        ctl.edit_selected(text=texto)
    assert ctl.doc.items[0].text == "Hola" and ctl.stack.count() == 1
    ctl.undo()
    assert ctl.doc.items[0].text == "Texto"


def test_editar_con_el_mismo_valor_no_agrega_historial(ctl):
    ctl.doc.items.append(TextLabel("a1", (10.0, 10.0), "Texto"))
    ctl.select("a1")
    ctl.edit_selected(text="Texto")
    assert not ctl.stack.canUndo()


def test_nudge_mueve_y_fusiona_pulsaciones_seguidas(ctl):
    _con_marcador(ctl)
    ctl.select("a1")
    for _ in range(3):
        ctl.nudge(1.0, 0.0)
    assert ctl.doc.items[0].rect.x == 103 and ctl.stack.count() == 1
    ctl.undo()
    assert ctl.doc.items[0].rect.x == 100


def test_deshacer_una_creacion_deselecciona(ctl):
    ctl.set_tool(Tool.STEP)
    ctl.press((10.0, 10.0), TOL)
    assert ctl.selected_id == "a1"
    ctl.undo()
    assert ctl.selected_id is None


def test_set_doc_reinicia_historial_seleccion_y_herramienta(ctl):
    _con_marcador(ctl)
    ctl.set_tool(Tool.STEP)
    ctl.press((10.0, 10.0), TOL)
    ctl.set_doc(AnnotationDoc(Path("y.png"), (100, 100)))
    assert not ctl.stack.canUndo() and ctl.selected_id is None and ctl.tool is Tool.SELECT


def test_emite_changed_al_modificar(ctl):
    cambios = []
    ctl.changed.connect(lambda: cambios.append(1))
    ctl.set_tool(Tool.MARKER)
    drag(ctl, (100.0, 100.0), (200.0, 160.0))
    assert cambios


def test_sin_documento_los_gestos_no_truenan(qapp):
    c = EditController()
    c.press((1.0, 1.0), TOL)
    c.move((2.0, 2.0))
    c.release((2.0, 2.0))
    c.delete_selected()
    c.nudge(1.0, 1.0)
    assert c.cursor_at((1.0, 1.0), TOL) == Qt.ArrowCursor


def test_cursor_segun_herramienta_asa_y_anotacion(ctl):
    _con_marcador(ctl)
    assert ctl.cursor_at((700.0, 500.0), TOL) == Qt.ArrowCursor
    assert ctl.cursor_at((100.0, 150.0), TOL) == Qt.SizeAllCursor
    ctl.select("a1")
    assert ctl.cursor_at((300.0, 200.0), TOL) == Qt.SizeFDiagCursor
    ctl.set_tool(Tool.MARKER)
    assert ctl.cursor_at((700.0, 500.0), TOL) == Qt.CrossCursor
