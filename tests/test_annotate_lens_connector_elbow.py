"""Conector de la lupa en codo: tramos solo horizontales y verticales, un solo trazo con la esquina en inglete."""

import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image

from core.annotate import edit, lens, style
from core.annotate.bounds import item_box
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, ConnectorRoute, LensShape, Magnifier, Rect
from core.annotate.primitives import PLine, PPath, magnifier_primitives
from core.annotate.svg import export_png, primitive_to_svg

SRC = Rect(100.0, 100.0, 100.0, 60.0)
TOL = 6.0
CODO = ConnectorRoute.ELBOW


def _lupa(center, shape=LensShape.ROUNDED, **kw):
    return Magnifier("l", SRC, center, 2.0, shape, connector_route=CODO, **kw)   # lente de 200 x 120


def _es_ortogonal(path):
    return all(a[0] == b[0] or a[1] == b[1] for a, b in zip(path, path[1:]))


# --- ruta pura -------------------------------------------------------------------------------------------

def test_dos_extremos_horizontales_que_se_miran_dan_una_z_con_el_tramo_vertical_a_la_mitad():
    assert lens.orthogonal_path((0.0, 0.0), (1, 0), (100.0, 60.0), (-1, 0)) == [(0.0, 0.0), (50.0, 0.0), (50.0, 60.0), (100.0, 60.0)]


def test_dos_extremos_verticales_que_se_miran_tambien():
    assert lens.orthogonal_path((0.0, 0.0), (0, 1), (60.0, 100.0), (0, -1)) == [(0.0, 0.0), (0.0, 50.0), (60.0, 50.0), (60.0, 100.0)]


def test_si_ya_estan_alineados_se_reduce_a_una_recta():
    assert lens.orthogonal_path((0.0, 30.0), (1, 0), (100.0, 30.0), (-1, 0)) == [(0.0, 30.0), (100.0, 30.0)]


def test_uno_horizontal_y_otro_vertical_dan_una_ele():
    assert lens.orthogonal_path((0.0, 0.0), (1, 0), (100.0, 60.0), (0, -1)) == [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0)]
    assert lens.orthogonal_path((0.0, 0.0), (0, 1), (100.0, 60.0), (-1, 0)) == [(0.0, 0.0), (0.0, 60.0), (100.0, 60.0)]


def test_si_los_dos_miran_al_mismo_lado_el_codo_sale_de_los_dos():
    camino = lens.orthogonal_path((0.0, 0.0), (1, 0), (100.0, 60.0), (1, 0))
    assert camino[1][0] == camino[2][0] == 100.0 + lens.ELBOW_CLEARANCE and _es_ortogonal(camino)


# --- conector automatico en codo -------------------------------------------------------------------------

@pytest.mark.parametrize("centro", [(500.0, 130.0), (500.0, 330.0), (500.0, 40.0), (-200.0, 330.0), (150.0, 400.0), (330.0, 400.0), (150.0, -150.0)])
@pytest.mark.parametrize("forma", [LensShape.ROUNDED, LensShape.ELLIPSE, LensShape.CIRCLE])
def test_en_cualquier_posicion_el_codo_solo_tiene_tramos_rectos_horizontales_o_verticales(centro, forma):
    path = lens.connector_path(_lupa(centro, forma))
    assert len(path) >= 2 and _es_ortogonal(path)


def test_a_la_derecha_y_mas_abajo_sin_solaparse_sale_una_z_de_mitad_a_mitad():
    m = _lupa((500.0, 330.0))
    box = lens.lens_rect(m)
    path = lens.connector_path(m)
    assert path[0] == (SRC.right, SRC.center[1]) and path[-1] == (box.x, box.center[1])
    assert len(path) == 4 and path[1][1] == path[0][1] and path[2][1] == path[-1][1]


def test_con_tramo_compartido_sigue_siendo_una_recta_pareja():
    path = lens.connector_path(_lupa((500.0, 150.0)))
    assert len(path) == 2 and path[0][1] == path[1][1]


def test_el_codo_de_un_ovalo_sale_por_los_puntos_de_sus_ejes_que_estan_en_su_perimetro():
    m = _lupa((500.0, 330.0), LensShape.ELLIPSE)
    path = lens.connector_path(m)
    assert path[0] == (SRC.right, SRC.center[1])                      # el extremo derecho del ovalo del origen


def test_el_trazado_recto_no_tiene_ruta_en_codo_y_sigue_igual():
    m = replace(_lupa((500.0, 330.0)), connector_route=ConnectorRoute.STRAIGHT)
    assert lens.connector_path(m) == [] and len(lens.connector_segments(m)) == 1
    [(a, b)] = lens.connector_segments(m)
    assert a != b and not _es_ortogonal([a, b])                       # la diagonal de siempre


def test_los_segmentos_del_codo_son_los_pares_consecutivos_de_su_camino():
    m = _lupa((500.0, 330.0))
    path = lens.connector_path(m)
    assert lens.connector_segments(m) == list(zip(path, path[1:]))


def test_extremos_a_mano_en_codo_salen_hacia_afuera_de_su_lado():
    m = replace(_lupa((500.0, 330.0)), connector_start=(0.5, 0.0))     # arriba del origen
    path = lens.connector_path(m)
    assert path[0] == (150.0, SRC.y) and path[1][0] == 150.0 and path[1][1] != path[0][1]   # sale vertical
    assert _es_ortogonal(path)


def test_las_asas_del_conector_estan_en_los_extremos_del_codo():
    m = _lupa((500.0, 330.0))
    handles = edit.item_handles(m)
    path = lens.connector_path(m)
    assert handles[edit.Handle.CONN_START] == path[0] and handles[edit.Handle.CONN_END] == path[-1]


def test_un_clic_sobre_cualquier_tramo_del_codo_selecciona_la_lupa():
    m = _lupa((500.0, 330.0))
    path = lens.connector_path(m)
    medio = ((path[1][0] + path[2][0]) / 2, (path[1][1] + path[2][1]) / 2)   # el tramo vertical del medio
    assert edit.hit_lens_part(m, medio, TOL) == "connector"


# --- primitivas ------------------------------------------------------------------------------------------

def _caminos(prims):
    return [p for p in prims if isinstance(p, PPath)]


def test_el_codo_se_dibuja_como_caminos_de_un_solo_trazo_y_la_recta_sigue_siendo_una_linea():
    codo = magnifier_primitives(_lupa((500.0, 330.0)), 1.0)
    assert len(_caminos(codo)) == 2 and not [p for p in codo if isinstance(p, PLine)]   # contorno navy + color
    recta = magnifier_primitives(replace(_lupa((500.0, 330.0)), connector_route=ConnectorRoute.STRAIGHT), 1.0)
    assert not _caminos(recta) and [p for p in recta if isinstance(p, PLine)]
    alineado = magnifier_primitives(_lupa((500.0, 150.0)), 1.0)      # un codo sin esquinas es una linea
    assert not _caminos(alineado) and [p for p in alineado if isinstance(p, PLine)]


def test_el_resplandor_del_conector_en_codo_son_nueve_caminos_con_su_misma_opacidad():
    m = _lupa((500.0, 330.0), connector_glow=True)
    dorados = [p for p in _caminos(magnifier_primitives(m, 1.0)) if p.stroke == style.GLOW_GOLD]
    assert len(dorados) == len(style.GLOW_RINGS)
    assert max(p.width for p in dorados) > min(p.width for p in dorados)


def test_la_caja_de_la_lupa_incluye_el_camino_del_codo():
    m = _lupa((500.0, 330.0))
    doc = AnnotationDoc(None, (1000, 700), [m], style_scale=1.0)
    box = item_box(doc, m, 1.0)
    path = lens.connector_path(m)
    assert all(box.x <= x <= box.right and box.y <= y <= box.bottom for x, y in path)


def test_el_svg_del_camino_lleva_esquinas_en_inglete_y_rayas_si_las_hay():
    prim = PPath(((0.0, 0.0), (50.0, 0.0), (50.0, 40.0)), "#112233", 4.0, 0.6, (12.0, 8.0))
    svg = primitive_to_svg(prim)
    assert 'stroke-linejoin="miter"' in svg and "stroke-dasharray" in svg and 'points="0.00,0.00 50.00,0.00 50.00,40.00"' in svg


def _export(tmp_path, m, fondo=(255, 255, 255)):
    Image.new("RGB", (1000, 700), fondo).save(tmp_path / "f.png")
    doc = AnnotationDoc(tmp_path / "f.png", (1000, 700), [m], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def test_la_esquina_del_codo_no_tiene_muesca_y_qt_dibuja_igual_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    m = replace(_lupa((500.0, 330.0)), connector_width=8.0, connector_color="#FF0000")
    path = lens.connector_path(m)
    esquina = path[1]                                                  # primer codo
    exterior = (round(esquina[0] + 3), round(esquina[1] - 3))          # el hueco que dejaria un remate recto
    img = _export(tmp_path, m)
    assert img.getpixel(exterior)[1] < 200                             # pintado (no es el fondo blanco)
    qimg = QImage(1000, 700, QImage.Format_RGB32)
    qimg.fill(QColor(255, 255, 255))
    painter = QPainter(qimg)
    paint_primitives(painter, [p for p in magnifier_primitives(m, 1.0) if not hasattr(p, "key")])
    painter.end()
    qt = QColor(qimg.pixel(*exterior))
    assert qt.green() < 200


# --- guardar y abrir -------------------------------------------------------------------------------------

def test_el_trazado_se_guarda_y_un_proyecto_viejo_abre_recto():
    m = _lupa((500.0, 330.0))
    assert item_from_dict(item_to_dict(m)) == m and item_to_dict(m)["connector_route"] == "elbow"
    viejo = item_to_dict(m)
    viejo.pop("connector_route")
    assert item_from_dict(viejo).connector_route is ConnectorRoute.STRAIGHT


@pytest.mark.parametrize("malo", [None, "curvo", 3, True])
def test_un_trazado_invalido_vuelve_a_recto(malo):
    d = item_to_dict(_lupa((500.0, 330.0)))
    d["connector_route"] = malo
    assert item_from_dict(d).connector_route is ConnectorRoute.STRAIGHT


# --- panel -----------------------------------------------------------------------------------------------

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_el_selector_de_trazado_cambia_el_conector_en_un_paso_y_se_oculta_sin_conector(qapp, tmp_path):
    from ui.annotate.tab import AnnotateTab

    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    tab = AnnotateTab()
    tab.resize(1300, 800)
    tab.show()
    QApplication.processEvents()
    tab.load_capture(tmp_path / "cap.png")
    tab.doc.items.append(replace(_lupa((500.0, 330.0)), connector_route=ConnectorRoute.STRAIGHT))
    tab.controller.select("l")
    QApplication.processEvents()
    p = tab.panel
    assert p._lens_connector_route.currentData() == "straight" and p._lens_form.isRowVisible(p._lens_connector_route_row)
    pasos = tab.controller.stack.count()
    p._lens_connector_route.setCurrentIndex(p._lens_connector_route.findData("elbow"))
    assert tab.controller.selected_item().connector_route is ConnectorRoute.ELBOW
    assert tab.controller.stack.count() == pasos + 1
    tab.controller.undo()
    QApplication.processEvents()
    assert tab.controller.selected_item().connector_route is ConnectorRoute.STRAIGHT
    assert p._lens_connector_route.currentData() == "straight"
    p._lens_connector.setChecked(False)
    QApplication.processEvents()
    assert not p._lens_form.isRowVisible(p._lens_connector_route_row)
