"""Flecha y linea con codo: un camino de tramos horizontales y verticales (como el conector de la lupa), un solo trazo con la
esquina en inglete; las puntas siguen la direccion del tramo en que terminan."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import edit
from core.annotate.bounds import item_box
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Arrow, ConnectorRoute, HeadStyle, LineStyle
from core.annotate.primitives import PLine, PPath, PPolygon, arrow_path, arrow_primitives
from core.annotate.svg import export_png, primitive_to_svg

CODO = ConnectorRoute.ELBOW
A = Arrow("a", (100.0, 100.0), (300.0, 220.0), route=CODO)
TOL = 6.0


def test_por_defecto_es_recta_y_no_cambia_nada():
    recta = Arrow("a", (100.0, 100.0), (300.0, 220.0))
    assert recta.route is ConnectorRoute.STRAIGHT and arrow_path(recta) == [(100.0, 100.0), (300.0, 220.0)]
    assert [type(p).__name__ for p in arrow_primitives(recta, 1.0)] == ["PLine", "PLine", "PPolygon", "PPolygon"]


def test_el_codo_sale_en_horizontal_y_llega_en_vertical():
    assert arrow_path(A) == [(100.0, 100.0), (300.0, 100.0), (300.0, 220.0)]


def test_invertido_sale_en_vertical_y_llega_en_horizontal():
    assert arrow_path(replace(A, elbow_vertical_first=True)) == [(100.0, 100.0), (100.0, 220.0), (300.0, 220.0)]


@pytest.mark.parametrize("end", [(300.0, 100.0), (100.0, 220.0)])
def test_alineada_se_reduce_a_una_recta(end):
    alineada = replace(A, end=end)
    assert len(arrow_path(alineada)) == 2
    assert all(isinstance(p, PLine) or not isinstance(p, PPath) for p in arrow_primitives(alineada, 1.0))


def test_el_codo_es_un_solo_trazo_con_resplandor_y_la_punta_mira_por_el_ultimo_tramo():
    prims = arrow_primitives(A, 1.0)
    assert [type(p).__name__ for p in prims] == ["PPath", "PPath", "PPolygon", "PPolygon"]
    assert prims[1].points == ((100.0, 100.0), (300.0, 100.0), (300.0, 220.0)) and prims[1].width == 5.0
    punta = prims[3]
    assert punta.points[0] == (300.0, 220.0)
    assert punta.points[1][1] < 220.0 and punta.points[2][1] < 220.0   # la base queda ARRIBA: el ultimo tramo baja
    assert abs(punta.points[1][0] - punta.points[2][0]) > 5            # y se abre a los lados


def test_punta_inicial_mira_hacia_afuera_del_primer_tramo():
    ambas = replace(A, head_start=HeadStyle.ARROW, glow=False)
    inicio = [p for p in arrow_primitives(ambas, 1.0) if isinstance(p, PPolygon) and p.points[0] == (100.0, 100.0)][0]
    assert inicio.points[1][0] > 100.0 and inicio.points[2][0] > 100.0   # el primer tramo va a la derecha


def test_las_rayas_viajan_en_el_camino():
    camino = [p for p in arrow_primitives(replace(A, line_style=LineStyle.DASHED, glow=False), 1.0) if isinstance(p, PPath)][0]
    assert camino.dash is not None


# --- Z: dos esquinas ----------------------------------------------------------------------------------

Z = replace(A, elbow_z=True)


def test_la_z_sale_en_horizontal_sube_o_baja_a_la_mitad_y_llega_en_horizontal():
    assert arrow_path(Z) == [(100.0, 100.0), (200.0, 100.0), (200.0, 220.0), (300.0, 220.0)]


def test_la_z_invertida_sale_en_vertical_con_el_tramo_del_medio_horizontal():
    assert arrow_path(replace(Z, elbow_vertical_first=True)) == [(100.0, 100.0), (100.0, 160.0), (300.0, 160.0), (300.0, 220.0)]


def test_el_tramo_del_medio_se_coloca_con_elbow_split():
    assert arrow_path(replace(Z, elbow_split=0.25))[1:3] == [(150.0, 100.0), (150.0, 220.0)]
    assert arrow_path(replace(Z, elbow_split=0.9))[1:3] == [(280.0, 100.0), (280.0, 220.0)]


@pytest.mark.parametrize("split", [0.0, 1.0])
def test_en_los_extremos_la_z_degenera_en_una_ele_sin_puntos_repetidos(split):
    camino = arrow_path(replace(Z, elbow_split=split))
    assert len(camino) == 3 and len(set(camino)) == 3


def test_z_alineada_es_una_recta():
    assert len(arrow_path(replace(Z, end=(300.0, 100.0)))) == 2


def test_la_z_es_un_solo_trazo_y_la_punta_mira_por_el_ultimo_tramo_horizontal():
    prims = arrow_primitives(Z, 1.0)
    assert [type(p).__name__ for p in prims] == ["PPath", "PPath", "PPolygon", "PPolygon"]
    assert len(prims[1].points) == 4
    punta = prims[3]
    assert punta.points[0] == (300.0, 220.0) and punta.points[1][0] < 300.0 and punta.points[2][0] < 300.0


def test_clic_en_los_tres_tramos_de_la_z():
    for p in [(150.0, 100.0), (200.0, 160.0), (250.0, 220.0)]:
        assert edit.hit_item(Z, p, TOL, 1.0)
    assert not edit.hit_item(Z, (150.0, 160.0), TOL, 1.0)


def test_la_z_ida_y_vuelta_del_json_y_valores_invalidos():
    z = replace(Z, elbow_split=0.3, elbow_vertical_first=True)
    assert item_from_dict(item_to_dict(z)) == z
    datos = item_to_dict(Z)
    datos["elbow_z"], datos["elbow_split"] = "si", 7
    assert not item_from_dict(datos).elbow_z and item_from_dict(datos).elbow_split == 0.5
    del datos["elbow_z"], datos["elbow_split"]
    assert not item_from_dict(datos).elbow_z


def test_exporta_la_z(tmp_path):
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "c.png")
    doc = AnnotationDoc(Path(tmp_path / "c.png"), (400, 300), [replace(Z, color="#FF0000", glow=False)], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    img = Image.open(tmp_path / "o.png").convert("RGB")
    assert img.getpixel((150, 100)) == img.getpixel((200, 160)) == img.getpixel((250, 220)) == (255, 0, 0)
    assert img.getpixel((150, 160)) == (255, 255, 255)


# --- seleccion -------------------------------------------------------------------------------------------

def test_clic_sobre_cualquiera_de_los_dos_tramos_selecciona_y_en_la_diagonal_vacia_no():
    assert edit.hit_item(A, (200.0, 100.0), TOL, 1.0)      # tramo horizontal
    assert edit.hit_item(A, (300.0, 160.0), TOL, 1.0)      # tramo vertical
    assert not edit.hit_item(A, (200.0, 160.0), TOL, 1.0)  # donde pasaria la recta
    recta = replace(A, route=ConnectorRoute.STRAIGHT)
    assert edit.hit_item(recta, (200.0, 160.0), TOL, 1.0) and not edit.hit_item(recta, (200.0, 100.0), TOL, 1.0)


def test_las_asas_siguen_en_los_extremos_y_arrastrarlas_mueve_el_extremo():
    assert set(edit.item_handles(A).values()) == {A.start, A.end}
    movida = edit.resize_item(A, edit.Handle.END, (400.0, 300.0))
    assert movida.end == (400.0, 300.0) and movida.route is CODO


def test_mover_conserva_el_codo():
    movida = edit.move_item(A, 10.0, 5.0)
    assert movida.route is CODO and arrow_path(movida)[1] == (310.0, 105.0)


# --- guardado ------------------------------------------------------------------------------------------

def test_ida_y_vuelta_del_json():
    invertida = replace(A, elbow_vertical_first=True)
    assert item_from_dict(item_to_dict(invertida)) == invertida
    assert item_from_dict(item_to_dict(A)) == A


def test_un_proyecto_viejo_o_un_dato_invalido_abre_recto():
    datos = item_to_dict(A)
    del datos["route"], datos["elbow_vertical_first"]
    assert item_from_dict(datos).route is ConnectorRoute.STRAIGHT and not item_from_dict(datos).elbow_vertical_first
    datos["route"], datos["elbow_vertical_first"] = "zigzag", "si"
    assert item_from_dict(datos).route is ConnectorRoute.STRAIGHT and not item_from_dict(datos).elbow_vertical_first


# --- dibujo ----------------------------------------------------------------------------------------------

def test_el_svg_lleva_un_solo_trazo_por_capa_y_las_cotas_cubren_el_codo():
    ruta = [p for p in arrow_primitives(A, 1.0) if isinstance(p, PPath)][0]
    assert primitive_to_svg(ruta).count("<polyline") == 1
    doc = AnnotationDoc(Path("x.png"), (400, 300), [A], style_scale=1.0)
    box = item_box(doc, A, 1.0)
    assert box.x <= 100.0 and box.y <= 100.0 and box.right >= 300.0 and box.bottom >= 220.0


def test_exporta_a_png(tmp_path):
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "c.png")
    doc = AnnotationDoc(Path(tmp_path / "c.png"), (400, 300), [replace(A, color="#FF0000", glow=False)], style_scale=1.0)
    out = tmp_path / "o.png"
    export_png(doc, out)
    img = Image.open(out).convert("RGB")
    assert img.getpixel((200, 100)) == (255, 0, 0)       # sobre el tramo horizontal
    assert img.getpixel((300, 160)) == (255, 0, 0)       # sobre el vertical
    assert img.getpixel((200, 160)) == (255, 255, 255)   # la diagonal queda vacia
