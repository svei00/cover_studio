import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest

from core.annotate import edit
from core.annotate.bounds import required_padding
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, ArrowSide, Marker, Rect
from core.annotate.primitives import PLine, PPolygon, marker_arrow, marker_primitives

R = Rect(100, 100, 200, 80)
M = Marker("m", R, ArrowSide.RIGHT)
AUTO_ARROW = ((378.0, 140.0), (306.0, 140.0))   # cola y punta de la flecha automatica del lado derecho (escala 1)
ARROWS = {"m": AUTO_ARROW}


def _doc(*items, size=(800, 500)):
    return AnnotationDoc(Path("x.png"), size, list(items), style_scale=1.0)


# --- modelo y primitivas ---------------------------------------------------

def test_sin_puntos_propios_la_flecha_es_la_automatica():
    assert not M.custom_arrow
    assert marker_arrow(M, _doc(M), 1.0) == AUTO_ARROW


def test_con_puntos_propios_la_flecha_se_dibuja_ahi():
    m = replace(M, arrow_start=(500.0, 300.0), arrow_tip=(420.0, 250.0))
    assert m.custom_arrow and marker_arrow(m, _doc(m), 1.0) == ((500.0, 300.0), (420.0, 250.0))
    lines = [p for p in marker_primitives(m, 1.0, ArrowSide.RIGHT) if isinstance(p, PLine) and p.opacity == 1.0]
    assert [(p.a, p.b) for p in lines] == [((500.0, 300.0), (420.0, 250.0))]
    # y la punta (triangulo) termina en la punta propia
    head = [p for p in marker_primitives(m, 1.0, ArrowSide.RIGHT) if isinstance(p, PPolygon) and p.fill][0]
    assert head.points[0] == (420.0, 250.0)


def test_un_marcador_sin_flecha_no_la_dibuja_aunque_tenga_puntos():
    m = replace(M, arrow=ArrowSide.NONE, arrow_start=(500.0, 300.0), arrow_tip=(420.0, 250.0))
    assert marker_arrow(m, _doc(m), 1.0) is None
    assert not [p for p in marker_primitives(m, 1.0, ArrowSide.NONE) if isinstance(p, (PLine, PPolygon))]


def test_la_flecha_movida_a_mano_cuenta_para_el_margen():
    lejos = replace(M, arrow_start=(790.0, 140.0), arrow_tip=(830.0, 140.0))   # se sale de la imagen por la derecha
    assert required_padding(_doc(lejos)) > required_padding(_doc(M))


# --- edicion ---------------------------------------------------------------

def test_las_asas_de_la_flecha_aparecen_solo_si_el_marcador_la_lleva():
    con = edit.item_handles(M, ARROWS)
    assert con[edit.Handle.START] == AUTO_ARROW[0] and con[edit.Handle.END] == AUTO_ARROW[1] and len(con) == 10
    assert len(edit.item_handles(M)) == 8   # sin saber donde esta la flecha: solo las del recuadro


def test_arrastrar_la_punta_o_la_cola_fija_los_dos_extremos():
    punta = edit.resize_item(M, edit.Handle.END, (450.0, 300.0), arrows=ARROWS)
    assert (punta.arrow_start, punta.arrow_tip) == (AUTO_ARROW[0], (450.0, 300.0))   # la cola se queda
    cola = edit.resize_item(M, edit.Handle.START, (500.0, 100.0), arrows=ARROWS)
    assert (cola.arrow_start, cola.arrow_tip) == ((500.0, 100.0), AUTO_ARROW[1])     # la punta se queda
    assert edit.resize_item(M, edit.Handle.END, (1, 1)) == M                          # sin flecha conocida: nada


def test_arrastrar_el_asa_de_la_flecha_prefiere_la_mas_cercana():
    assert edit.hit_handle(M, (306.0, 140.0), 6, ARROWS) is edit.Handle.END
    assert edit.hit_handle(M, (378.0, 142.0), 6, ARROWS) is edit.Handle.START
    assert edit.hit_handle(M, (300.0, 100.0), 6, ARROWS) is edit.Handle.NE   # la esquina del recuadro sigue siendo suya


def test_mover_solo_la_flecha_deja_el_recuadro_quieto():
    movida = edit.move_item(M, 10, -20, "arrow", ARROWS)
    assert movida.rect == R
    assert movida.arrow_start == (388.0, 120.0) and movida.arrow_tip == (316.0, 120.0)
    assert edit.move_item(M, 10, -20, "arrow") == M   # sin flecha conocida no inventa nada


def test_mover_el_marcador_arrastra_su_flecha_propia_y_la_automatica_se_acomoda_sola():
    propia = replace(M, arrow_start=(500.0, 300.0), arrow_tip=(420.0, 250.0))
    movido = edit.move_item(propia, 10, 5)
    assert movido.rect == Rect(110, 105, 200, 80)
    assert (movido.arrow_start, movido.arrow_tip) == ((510.0, 305.0), (430.0, 255.0))
    auto = edit.move_item(M, 10, 5)
    assert not auto.custom_arrow


def test_la_parte_bajo_el_mouse_distingue_flecha_de_recuadro():
    assert edit.hit_marker_part(M, (350, 140), 6, ARROWS) == "arrow"     # sobre el cuerpo de la flecha
    assert edit.hit_marker_part(M, (300, 140), 6, ARROWS) is None        # el borde del recuadro es mas cercano
    assert edit.hit_marker_part(M, (200, 140), 6, ARROWS) is None        # el interior
    assert edit.hit_marker_part(M, (350, 140), 6) is None                # sin flecha conocida


# --- archivo ---------------------------------------------------------------

def test_la_flecha_propia_se_guarda_y_se_recupera():
    m = replace(M, arrow_start=(500.0, 300.0), arrow_tip=(420.0, 250.0))
    assert item_from_dict(item_to_dict(m)) == m
    assert item_from_dict(item_to_dict(M)) == M


def test_un_proyecto_viejo_o_con_datos_invalidos_abre_con_flecha_automatica():
    data = item_to_dict(M)
    del data["arrow_start"], data["arrow_tip"]
    assert not item_from_dict(data).custom_arrow
    for start, tip in [([1, 2], None), (None, [1, 2]), ("x", [1, 2]), ([1], [1, 2]), ([True, 2], [3, 4])]:
        data = item_to_dict(M)
        data["arrow_start"], data["arrow_tip"] = start, tip
        assert not item_from_dict(data).custom_arrow   # los dos o ninguno


# --- interfaz --------------------------------------------------------------

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    t.controller.set_style_scale(1.0)
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)


@pytest.fixture
def marker(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (200, 200), (400, 280))
    tab.tool_buttons[Tool.SELECT].click()   # la herramienta sigue activa: se sale para editar
    QApplication.processEvents()
    return tab.doc.items[0]


def _arrow(tab):
    return tab.controller.marker_arrows()[tab.doc.items[0].id]


def test_arrastrar_la_punta_la_alarga_y_es_un_solo_paso(tab, marker):
    cola, punta = _arrow(tab)
    pasos = tab.controller.stack.count()
    drag(tab.canvas, punta, (punta[0] + 60, punta[1] + 40))
    m = tab.doc.items[0]
    assert m.custom_arrow and m.rect == marker.rect
    assert m.arrow_start == pytest.approx(cola) and m.arrow_tip == pytest.approx((punta[0] + 60, punta[1] + 40))
    assert tab.controller.stack.count() == pasos + 1
    tab.controller.undo()
    assert not tab.doc.items[0].custom_arrow   # vuelve a la automatica


def test_arrastrar_la_cola_la_acorta_o_la_gira(tab, marker):
    cola, punta = _arrow(tab)
    drag(tab.canvas, cola, (cola[0] - 30, cola[1] + 60))
    m = tab.doc.items[0]
    assert m.arrow_tip == pytest.approx(punta)
    assert m.arrow_start == pytest.approx((cola[0] - 30, cola[1] + 60))


def test_arrastrar_el_cuerpo_de_la_flecha_la_mueve_sin_tocar_el_recuadro(tab, marker):
    cola, punta = _arrow(tab)
    medio = ((cola[0] + punta[0]) / 2, (cola[1] + punta[1]) / 2)
    tab.controller.select(None)   # sin seleccionar antes: el mismo clic la selecciona y la mueve
    drag(tab.canvas, medio, (medio[0] + 25, medio[1] + 70))
    m = tab.doc.items[0]
    assert m.rect == marker.rect
    assert m.arrow_start == pytest.approx((cola[0] + 25, cola[1] + 70))
    assert m.arrow_tip == pytest.approx((punta[0] + 25, punta[1] + 70))
    assert tab.controller.selected_id == m.id


def test_mover_el_recuadro_por_el_borde_arrastra_la_flecha_propia(tab, marker):
    cola, punta = _arrow(tab)
    drag(tab.canvas, punta, (punta[0] + 40, punta[1] + 40))     # flecha propia
    arrow = _arrow(tab)
    drag(tab.canvas, (200, 215), (230, 225))                     # borde izquierdo del recuadro (no el asa del medio)
    m = tab.doc.items[0]
    assert m.rect.x == pytest.approx(marker.rect.x + 30) and m.rect.y == pytest.approx(marker.rect.y + 10)
    assert _arrow(tab)[0] == pytest.approx((arrow[0][0] + 30, arrow[0][1] + 10))
    assert _arrow(tab)[1] == pytest.approx((arrow[1][0] + 30, arrow[1][1] + 10))


def test_un_recuadro_sin_flecha_no_tiene_asas_de_flecha(tab):
    tab.tool_buttons[Tool.MARKER_PLAIN].click()
    drag(tab.canvas, (200, 200), (400, 280))
    assert tab.controller.marker_arrows() == {}
    assert len(edit.item_handles(tab.doc.items[0], tab.controller.marker_arrows())) == 8


def test_elegir_un_lado_en_el_panel_suelta_la_flecha_propia(tab, marker):
    cola, punta = _arrow(tab)
    drag(tab.canvas, punta, (punta[0] + 60, punta[1] + 40))
    panel = tab.panel
    assert not panel._marker_arrow_reset.isHidden()
    combo = panel._marker_arrow
    combo.setCurrentIndex(combo.findData(ArrowSide.LEFT.value))
    m = tab.doc.items[0]
    assert m.arrow is ArrowSide.LEFT and not m.custom_arrow
    assert panel._marker_arrow_reset.isHidden()


def test_recolocar_flecha_y_el_boton_de_restablecer(tab, marker):
    cola, punta = _arrow(tab)
    drag(tab.canvas, punta, (punta[0] + 60, punta[1] + 40))
    panel = tab.panel
    reset = panel._marker_arrow.parentWidget().layout().itemAt(1).widget()
    assert reset.isEnabled()                       # hay una flecha movida: el valor ya no es el de fabrica
    panel._marker_arrow_reset.click()
    assert not tab.doc.items[0].custom_arrow and tab.doc.items[0].arrow is ArrowSide.AUTO
    assert not reset.isEnabled()
    tab.controller.undo()                           # recolocar es un paso: se puede deshacer
    assert tab.doc.items[0].custom_arrow


def test_restablecer_el_lado_tambien_suelta_la_flecha_propia(tab, marker):
    cola, punta = _arrow(tab)
    drag(tab.canvas, punta, (punta[0] + 60, punta[1] + 40))
    tab.panel._marker_arrow.setCurrentIndex(tab.panel._marker_arrow.findData(ArrowSide.LEFT.value))
    tab.panel._marker_arrow.parentWidget().layout().itemAt(1).widget().click()
    m = tab.doc.items[0]
    assert m.arrow is ArrowSide.AUTO and not m.custom_arrow


def test_la_flecha_movida_se_exporta_donde_se_dejo(tab, marker, tmp_path):
    cola, punta = _arrow(tab)
    nueva_cola, nueva_punta = (500.0, 420.0), (560.0, 360.0)
    drag(tab.canvas, cola, nueva_cola)
    drag(tab.canvas, punta, nueva_punta)
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    img = Image.open(out).convert("RGB")
    mid = (int((nueva_cola[0] + nueva_punta[0]) / 2), int((nueva_cola[1] + nueva_punta[1]) / 2))
    r, g, b = img.getpixel(mid)
    assert (r, g, b) == pytest.approx((98, 17, 50), abs=25)      # el color de la flecha en su nuevo lugar
    r, g, b = img.getpixel((int(cola[0] - 10), int(cola[1])))     # y ya no esta donde estaba la automatica
    assert (r, g, b) == (255, 255, 255)
