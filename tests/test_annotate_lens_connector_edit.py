"""Conector de la lupa: extremos automaticos parejos, asas arrastrables que se pegan al borde, extremos que siguen
a la lupa (guardados como fraccion de la caja) y boton para recolocarlo."""

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core.annotate import edit, lens
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, LensShape, Magnifier, Rect

SRC = Rect(100.0, 100.0, 100.0, 60.0)
TOL = 6.0


def _lupa(center, shape=LensShape.ROUNDED, **kw):
    return Magnifier("l", SRC, center, 2.0, shape, **kw)   # lente de 200 x 120


# --- extremos automaticos --------------------------------------------------------------------------------

def test_a_la_derecha_y_a_la_misma_altura_el_conector_es_horizontal_de_lado_a_lado():
    m = _lupa((500.0, 130.0))                                         # centrado con el origen
    [(a, b)] = lens.connector_segments(m)
    assert a == (SRC.right, 130.0) and b == (lens.lens_rect(m).x, 130.0)


def test_si_comparten_altura_el_conector_sale_parejo_aunque_los_centros_no_coincidan():
    m = _lupa((500.0, 160.0))                                         # el lente esta mas abajo pero se solapan en y
    [(a, b)] = lens.connector_segments(m)
    assert a[1] == b[1]                                               # horizontal, no en diagonal
    box = lens.lens_rect(m)
    assert SRC.y <= a[1] <= SRC.bottom and box.y <= a[1] <= box.bottom   # y cae dentro de los dos lados


def test_debajo_y_alineado_el_conector_es_vertical():
    m = _lupa((150.0, 400.0))
    [(a, b)] = lens.connector_segments(m)
    assert a[0] == b[0] and a[1] == SRC.bottom and b[1] == lens.lens_rect(m).y


def test_sin_tramo_compartido_une_la_mitad_de_un_lado_con_la_mitad_del_otro():
    m = _lupa((500.0, 500.0))                                         # en diagonal, sin solaparse en x ni en y
    [(a, b)] = lens.connector_segments(m)
    assert {a, b} <= {(SRC.center[0], SRC.bottom), (lens.lens_rect(m).center[0], lens.lens_rect(m).y),
                      (SRC.right, SRC.center[1]), (lens.lens_rect(m).x, lens.lens_rect(m).center[1])}


def test_a_la_izquierda_y_arriba_tambien_salen_de_los_lados_que_se_miran():
    izq = lens.connector_segments(_lupa((-200.0, 130.0)))
    assert izq[0][0] == (SRC.x, 130.0)
    arriba = lens.connector_segments(_lupa((150.0, -200.0)))
    assert arriba[0][0] == (150.0, SRC.y)


def test_si_el_lente_tapa_al_origen_no_hay_conector():
    assert lens.connector_segments(_lupa((150.0, 130.0))) == []
    assert lens.connector_anchors(_lupa((150.0, 130.0))) is None


def test_sin_la_casilla_de_conector_no_hay_anchors_ni_asas():
    m = _lupa((500.0, 130.0), connector=False)
    assert lens.connector_anchors(m) is None
    assert edit.Handle.CONN_START not in edit.item_handles(m)


# --- pegarse al borde ------------------------------------------------------------------------------------

@pytest.mark.parametrize("p, esperado", [
    ((250.0, 130.0), (1.0, 0.5)),     # fuera, a la derecha: cae en el lado derecho
    ((150.0, 0.0), (0.5, 0.0)),       # arriba
    ((190.0, 130.0), (1.0, 0.5)),     # dentro y cerca del lado derecho: se manda a ese lado
    ((101.0, 130.0), (0.0, 0.5)),
    ((300.0, 300.0), (1.0, 1.0)),     # esquina
])
def test_border_fraction_de_un_rectangulo(p, esperado):
    assert lens.border_fraction(SRC, False, p) == pytest.approx(esperado)


def test_border_fraction_de_un_ovalo_cae_en_su_perimetro():
    u, v = lens.border_fraction(SRC, True, (400.0, 130.0))
    assert (u, v) == pytest.approx((1.0, 0.5))
    u, v = lens.border_fraction(SRC, True, (150.0, 300.0))
    assert (u, v) == pytest.approx((0.5, 1.0))
    u, v = lens.border_fraction(SRC, True, (400.0, 400.0))             # en diagonal: sobre la elipse
    x, y = (u - 0.5) * 2, (v - 0.5) * 2
    assert x * x + y * y == pytest.approx(1.0)


# --- asas ------------------------------------------------------------------------------------------------

def test_con_conector_la_lupa_suma_dos_asas_y_el_asa_lateral_que_coincide_les_cede_el_lugar():
    m = _lupa((500.0, 130.0))
    handles = edit.item_handles(m)
    a, b = lens.connector_anchors(m)
    assert handles[edit.Handle.CONN_START] == a and handles[edit.Handle.CONN_END] == b
    assert edit.Handle.E not in handles                               # el asa E del origen estaba justo ahi
    assert {edit.Handle.NW, edit.Handle.W, edit.Handle.LENS} <= set(handles)
    assert len(handles) == 8 + 1 + 2 - 1


def test_con_el_extremo_en_otro_lado_el_asa_lateral_vuelve():
    m = replace(_lupa((500.0, 130.0)), connector_start=(1.0, 0.1))
    handles = edit.item_handles(m)
    assert edit.Handle.E in handles
    assert handles[edit.Handle.CONN_START] == pytest.approx((SRC.right, SRC.y + 0.1 * SRC.h))


def test_arrastrar_el_extremo_del_origen_lo_pega_al_borde_y_no_toca_el_otro():
    m = _lupa((500.0, 130.0))
    nuevo = edit.resize_item(m, edit.Handle.CONN_START, (150.0, 90.0))   # arriba del origen, fuera
    assert nuevo.connector_start == pytest.approx((0.5, 0.0)) and nuevo.connector_end is None
    [(a, b)] = lens.connector_segments(nuevo)
    assert a == pytest.approx((150.0, SRC.y))
    assert b[0] == lens.lens_rect(nuevo).x                              # el otro extremo sigue automatico


def test_arrastrar_el_extremo_del_lente_usa_la_caja_del_lente():
    m = _lupa((500.0, 130.0))
    box = lens.lens_rect(m)
    nuevo = edit.resize_item(m, edit.Handle.CONN_END, (box.right + 30.0, box.y + 30.0))
    assert nuevo.connector_end == pytest.approx((1.0, 0.25)) and nuevo.connector_start is None


def test_los_extremos_puestos_a_mano_siguen_a_la_lupa_al_moverla_y_al_cambiar_el_zoom():
    m = replace(_lupa((500.0, 130.0)), connector_start=(1.0, 0.25), connector_end=(0.0, 0.75))
    a0, b0 = lens.connector_anchors(m)
    movida = edit.move_item(m, 40.0, 10.0)
    a1, b1 = lens.connector_anchors(movida)
    assert (a1[0] - a0[0], a1[1] - a0[1]) == pytest.approx((40.0, 10.0))
    assert (b1[0] - b0[0], b1[1] - b0[1]) == pytest.approx((40.0, 10.0))
    grande = replace(m, zoom=3.0)
    box = lens.lens_rect(grande)
    assert lens.connector_anchors(grande)[1] == pytest.approx((box.x, box.y + 0.75 * box.h))


def test_un_conector_a_mano_se_dibuja_como_una_sola_linea_incluso_en_un_lente_circular():
    m = _lupa((500.0, 130.0), shape=LensShape.CIRCLE)
    assert len(lens.connector_segments(m)) == 2                       # el cono automatico de siempre
    mano = replace(m, connector_start=(0.5, 0.0))
    assert len(lens.connector_segments(mano)) == 1


# --- tocar el conector -----------------------------------------------------------------------------------

def test_hacer_clic_sobre_el_conector_selecciona_la_lupa_y_lo_mueve_todo():
    m = _lupa((500.0, 130.0))
    medio = (350.0, 130.0)
    assert edit.hit_lens_part(m, medio, TOL) == "connector"
    assert edit.hit_test([m], medio, TOL, 1.0) == "l"
    movida = edit.move_item(m, 10.0, 5.0, "connector")
    assert movida.source.x == 110.0 and movida.lens_center == (510.0, 135.0)   # se mueve entera
    assert edit.hit_lens_part(m, (350.0, 200.0), TOL) is None


# --- guardar y abrir -------------------------------------------------------------------------------------

def test_los_extremos_se_guardan_y_un_proyecto_viejo_abre_con_conector_automatico():
    m = replace(_lupa((500.0, 130.0)), connector_start=(0.25, 1.0), connector_end=(0.0, 0.5))
    assert item_from_dict(item_to_dict(m)) == m
    viejo = item_to_dict(_lupa((500.0, 130.0)))
    viejo.pop("connector_start"), viejo.pop("connector_end")
    abierto = item_from_dict(viejo)
    assert abierto.connector_start is None and abierto.connector_end is None and not abierto.custom_connector


@pytest.mark.parametrize("malo", ["x", [0.5], [0.5, 2.0], [-0.1, 0.5], [True, 0.5], [0.5, 0.5, 0.5], 7])
def test_un_extremo_invalido_vuelve_a_automatico(malo):
    d = item_to_dict(_lupa((500.0, 130.0)))
    d["connector_start"], d["connector_end"] = malo, malo
    abierto = item_from_dict(d)
    assert abierto.connector_start is None and abierto.connector_end is None


# --- gesto y panel ---------------------------------------------------------------------------------------

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.annotate.controller import EditController  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (1000, 700)))
    return c


def test_arrastrar_el_asa_del_conector_es_un_solo_paso_de_deshacer_y_deshace_bien(ctl):
    m = _lupa((500.0, 130.0))
    ctl.doc.items.append(m)
    ctl.select("l")
    ctl.press(lens.connector_anchors(m)[1], TOL)                       # el asa del extremo del lente
    box = lens.lens_rect(m)
    ctl.move((box.x - 20.0, box.y - 15.0))
    ctl.move((box.x + 50.0, box.y - 15.0))                              # arriba del lente
    ctl.release((box.x + 50.0, box.y - 15.0))
    ahora = ctl.selected_item()
    assert ahora.connector_end == pytest.approx((0.25, 0.0)) and ahora.connector_start is None
    assert ctl.stack.count() == 1
    ctl.undo()
    assert ctl.selected_item().connector_end is None


def test_el_boton_recolocar_solo_aparece_con_extremos_a_mano_y_los_devuelve_a_automatico(qapp, tmp_path):
    from PIL import Image

    from ui.annotate.tab import AnnotateTab

    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    tab = AnnotateTab()
    tab.resize(1300, 800)
    tab.show()
    QApplication.processEvents()
    tab.load_capture(tmp_path / "cap.png")
    m = _lupa((500.0, 130.0))
    tab.doc.items.append(m)
    tab.controller.select("l")
    QApplication.processEvents()
    p = tab.panel
    assert not p._lens_form.isRowVisible(p._lens_connector_reset)
    tab.controller.edit_selected(_merge=False, connector_start=(0.5, 0.0))
    QApplication.processEvents()
    assert p._lens_form.isRowVisible(p._lens_connector_reset)
    p._lens_connector_reset.click()
    QApplication.processEvents()
    assert not tab.controller.selected_item().custom_connector
    assert not p._lens_form.isRowVisible(p._lens_connector_reset)
    tab.controller.undo()
    assert tab.controller.selected_item().connector_start == (0.5, 0.0)
