"""Llave, corchete, parentesis y cota (`Bracket`): geometria en cualquier angulo, texto o icono en el pico, edicion, proyecto y panel."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PIL import Image

from core.annotate import bracket as bg
from core.annotate import edit, style
from core.annotate.bounds import item_box, required_padding
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Bracket, BracketKind, Icon, IconKind, Rect, TextLabel, TipContent
from core.annotate.palette import BRAND_PALETTE
from core.annotate.primitives import PPolygon, PPolyline, PRect, PText, bracket_primitives, bracket_tip_item, label_box
from core.annotate.svg import export_png

H = Bracket("b", (100.0, 200.0), (400.0, 200.0))                    # horizontal, el pico va hacia ABAJO (la normal izquierda en pantalla)


def _local(b, p):
    """Coordenadas locales (a lo largo del tramo, hacia el lado del pico) de un punto de la imagen."""
    u, n, _ = bg.span(b)
    s = bg.side(b)
    dx, dy = p[0] - b.start[0], p[1] - b.start[1]
    return dx * u[0] + dy * u[1], (dx * n[0] + dy * n[1]) * s


# --- geometria ---------------------------------------------------------------------------------------------------


def test_el_tramo_su_normal_y_el_lado():
    u, n, length = bg.span(H)
    assert u == (1.0, 0.0) and n == (-0.0, 1.0) and length == 300.0
    assert bg.side(H) == 1.0 and bg.side(replace(H, flip=True)) == -1.0
    assert bg.outward(H) == (0.0, 1.0) and bg.outward(replace(H, flip=True)) == (0.0, -1.0)


def test_la_profundidad_por_defecto_crece_con_el_largo_entre_un_minimo_y_un_tope():
    assert bg.default_depth((0, 0), (40, 0)) == style.MIN_DEFAULT_BRACKET_DEPTH
    assert bg.default_depth((0, 0), (300, 0)) == pytest.approx(300 * style.DEFAULT_BRACKET_DEPTH_RATIO)
    assert bg.default_depth((0, 0), (3000, 0)) == style.MAX_DEFAULT_BRACKET_DEPTH


@pytest.mark.parametrize("kind", list(BracketKind))
def test_toda_forma_empieza_y_termina_en_los_extremos_de_su_tramo(kind):
    paths = bg.outline_paths(replace(H, kind=kind, depth=30.0))
    if kind is BracketKind.DIMENSION:
        assert len(paths) == 3                                                         # dos lineas de extension y la linea
        assert paths[0][0] == pytest.approx(H.start) and paths[1][0] == pytest.approx(H.end)
    else:
        assert len(paths) == 1
        assert paths[0][0] == pytest.approx(H.start) and paths[0][-1] == pytest.approx(H.end)


@pytest.mark.parametrize("kind", [BracketKind.BRACE, BracketKind.SQUARE, BracketKind.PAREN])
def test_el_punto_mas_lejano_del_tramo_es_el_pico_a_la_profundidad_pedida(kind):
    b = replace(H, kind=kind, depth=40.0)
    path = bg.outline_paths(b)[0]
    far = max(path, key=lambda p: _local(b, p)[1])
    assert _local(b, far)[1] == pytest.approx(40.0, abs=0.01)
    assert bg.tip_point(b) == pytest.approx((250.0, 240.0))                            # a la mitad del tramo, a `depth`
    if kind is not BracketKind.SQUARE:                                                 # (la barra del corchete es toda a `depth`)
        assert far == pytest.approx(bg.tip_point(b), abs=0.5)


@pytest.mark.parametrize("kind", [BracketKind.BRACE, BracketKind.SQUARE, BracketKind.PAREN])
def test_ninguna_forma_se_sale_del_lado_ni_de_la_profundidad(kind):
    b = replace(H, kind=kind, depth=40.0)
    for p in bg.outline_paths(b)[0]:
        x, y = _local(b, p)
        assert -0.01 <= x <= 300.01 and -0.01 <= y <= 40.01


@pytest.mark.parametrize("kind", [BracketKind.BRACE, BracketKind.SQUARE, BracketKind.PAREN])
def test_la_forma_es_simetrica_respecto_al_medio_del_tramo(kind):
    b = replace(H, kind=kind, depth=36.0)
    local = [_local(b, p) for p in bg.outline_paths(b)[0]]
    mirrored = sorted((300.0 - x, y) for x, y in local)
    assert [pytest.approx(q, abs=0.01) for q in sorted(local)] == mirrored


def test_la_llave_tiene_un_solo_pico_y_dos_arcos_suaves():
    b = replace(H, depth=40.0)
    path = bg.outline_paths(b)[0]
    ys = [_local(b, p)[1] for p in path]
    tip = ys.index(max(ys))
    assert path[tip] == pytest.approx(bg.tip_point(b), abs=0.5)
    assert ys[:tip] == sorted(ys[:tip]) or max(ys[:tip]) <= 40.0                       # sube hacia el pico
    mid_bar = [y for (x, _), y in zip((_local(b, p) for p in path), ys) if 30 < x < 120]
    assert all(abs(y - 20.0) < 0.5 for y in mid_bar)                                   # el tramo recto corre a la mitad de la altura


def test_el_corchete_tiene_esquinas_redondeadas_y_barra_a_la_profundidad():
    b = replace(H, kind=BracketKind.SQUARE, depth=40.0)
    path = bg.outline_paths(b)[0]
    bar = [p for p in path if abs(_local(b, p)[1] - 40.0) < 0.01]
    assert len(bar) >= 2 and min(_local(b, p)[0] for p in bar) > 0                     # la barra no llega a x = 0: ahi hay esquina
    assert not any(_local(b, p) == (0.0, 40.0) for p in path)                          # sin esquina viva


def test_la_cota_lleva_extension_con_resalte_y_la_linea_a_la_profundidad():
    b = replace(H, kind=BracketKind.DIMENSION, depth=30.0)
    ext1, ext2, line = bg.outline_paths(b)
    assert _local(b, ext1[-1])[1] == pytest.approx(30.0 + style.BRACKET_DIM_OVERSHOOT)
    assert _local(b, line[0]) == pytest.approx((0.0, 30.0)) and _local(b, line[1]) == pytest.approx((300.0, 30.0))
    assert _local(b, ext2[0]) == pytest.approx((300.0, 0.0))


@pytest.mark.parametrize("end", [(100.0, 500.0), (400.0, 500.0), (-100.0, 100.0), (100.0, 200.0 - 300.0)])
@pytest.mark.parametrize("flip", [False, True])
def test_en_cualquier_angulo_y_lado_la_forma_es_la_misma_en_locales(end, flip):
    """Rotar o invertir el tramo no cambia la forma vista desde el tramo (x a lo largo, y hacia el pico)."""
    ref = Bracket("r", (0.0, 0.0), (300.0, 0.0), depth=40.0)
    b = Bracket("b", (100.0, 200.0), end, depth=40.0, flip=flip)
    length = bg.span(b)[2]
    scaled = Bracket("s", (0.0, 0.0), (length, 0.0), depth=40.0)
    expected = [_local(scaled, p) for p in bg.outline_paths(scaled)[0]]
    got = [_local(b, p) for p in bg.outline_paths(b)[0]]
    assert got == [pytest.approx(q, abs=1e-6) for q in expected]
    assert _local(ref, bg.tip_point(ref))[1] == pytest.approx(40.0)


def test_el_lado_invertido_pone_la_forma_del_otro_lado_de_verdad():
    down, up = bg.tip_point(H), bg.tip_point(replace(H, flip=True))
    assert down[1] > 200.0 > up[1] and down[0] == pytest.approx(up[0])


def test_un_tramo_corto_conserva_la_profundidad_y_no_se_rompe():
    b = Bracket("b", (0.0, 0.0), (30.0, 0.0), depth=40.0)
    path = bg.outline_paths(b)[0]
    assert all(math.isfinite(v) for p in path for v in p)
    assert path[0] == pytest.approx((0.0, 0.0)) and path[-1] == pytest.approx((30.0, 0.0))
    assert max(abs(_local(b, p)[1]) for p in path) == pytest.approx(40.0, abs=0.01)


def test_un_tramo_de_largo_cero_no_dibuja_nada():
    b = Bracket("b", (50.0, 50.0), (50.0, 50.0))
    assert bg.outline_paths(b) == [] and bg.tip_point(b) is None and bracket_primitives(b, 1.0) == []
    assert bracket_tip_item(replace(b, tip=TipContent.TEXT, label="x"), 1.0) is None


def test_la_profundidad_nunca_baja_del_minimo_al_dibujar():
    path = bg.outline_paths(replace(H, depth=0.0))[0]
    assert max(_local(H, p)[1] for p in path) >= style.MIN_BRACKET_DEPTH - 0.01


# --- texto y medida -------------------------------------------------------------------------------------------------


def test_la_cota_sin_texto_muestra_su_medida_y_con_texto_el_suyo():
    cota = replace(H, kind=BracketKind.DIMENSION)
    assert bg.measure(cota) == 300 and bg.label_text(cota) == "300 px"
    assert bg.label_text(replace(cota, label="Ancho")) == "Ancho"
    assert bg.label_text(H) == "" and bg.label_text(replace(H, label="Total")) == "Total"


def test_la_medida_sigue_el_largo_aunque_el_tramo_vaya_en_diagonal():
    cota = Bracket("d", (0.0, 0.0), (30.0, 40.0), kind=BracketKind.DIMENSION)
    assert bg.label_text(cota) == "50 px"


# --- el pico: texto o icono, fuera de la forma ----------------------------------------------------------------------


def _tip(b, scale=1.0):
    return bracket_tip_item(b, scale)


def test_sin_contenido_o_sin_texto_el_pico_va_vacio():
    assert _tip(H) is None
    assert _tip(replace(H, tip=TipContent.TEXT)) is None                                # texto vacio (y no es cota)
    assert _tip(replace(H, tip=TipContent.TEXT, kind=BracketKind.DIMENSION)) is not None   # la cota muestra su medida


@pytest.mark.parametrize("end,flip", [((400.0, 200.0), False), ((400.0, 200.0), True), ((100.0, 500.0), False), ((100.0, 500.0), True)])
def test_el_texto_queda_fuera_pasando_el_pico_separado_lo_justo(end, flip):
    b = Bracket("b", (100.0, 200.0), end, depth=40.0, flip=flip, tip=TipContent.TEXT, label="Total")
    label = _tip(b)
    assert isinstance(label, TextLabel) and label.text == "Total"
    box = label_box(label, 1.0)
    tip, no = bg.tip_point(b), bg.outward(b)
    # el borde de la caja mas cercano al pico esta a `BRACKET_TIP_GAP` en la direccion del pico
    near = min((box.x, box.right), key=lambda v: abs(v - tip[0])) if abs(no[0]) > 0.5 else None
    if abs(no[1]) > 0.5:
        near_y = box.y if no[1] > 0 else box.bottom
        assert abs(near_y - tip[1]) == pytest.approx(style.BRACKET_TIP_GAP)
    else:
        near_x = box.x if no[0] > 0 else box.right
        assert abs(near_x - tip[0]) == pytest.approx(style.BRACKET_TIP_GAP)
    assert not (box.x <= tip[0] <= box.right and box.y <= tip[1] <= box.bottom)          # el pico no queda dentro de la caja


def test_el_texto_va_centrado_sobre_el_pico_en_una_llave_horizontal():
    b = replace(H, tip=TipContent.TEXT, label="Total", depth=30.0)
    box = label_box(_tip(b), 1.0)
    assert box.center[0] == pytest.approx(250.0) and box.y == pytest.approx(230.0 + style.BRACKET_TIP_GAP)


def test_el_texto_usa_el_estilo_y_el_tamano_elegidos_y_uno_desconocido_cae_a_nota():
    b = replace(H, tip=TipContent.TEXT, label="Error", label_preset="alerta2", label_size=40.0)
    t = _tip(b)
    assert t.size == 40.0 and t.bg == style.TEXT_PRESETS["alerta2"]["bg"]
    assert _tip(replace(b, label_preset="no-existe")).bg == style.TEXT_PRESETS["nota"]["bg"]


def test_el_icono_se_coloca_fuera_con_su_tipo_y_tamano():
    b = replace(H, tip=TipContent.ICON, tip_icon=IconKind.WARNING, tip_icon_size=20.0, depth=30.0)
    icon = _tip(b)
    assert isinstance(icon, Icon) and icon.kind is IconKind.WARNING and icon.size == 20.0
    assert icon.center[0] == pytest.approx(250.0)
    assert icon.center[1] == pytest.approx(230.0 + style.BRACKET_TIP_GAP + 20.0 * 1.15)


def test_el_texto_escala_con_el_documento_y_se_aleja_proporcionalmente():
    b = replace(H, tip=TipContent.TEXT, label="Total", depth=30.0)
    assert label_box(_tip(b, 2.0), 2.0).y == pytest.approx(230.0 + 2 * style.BRACKET_TIP_GAP)


# --- primitivas -----------------------------------------------------------------------------------------------------


def test_sin_resplandor_ni_pico_es_una_polilinea_por_trazo():
    b = replace(H, glow=False)
    prims = bracket_primitives(b, 1.0)
    assert [type(p).__name__ for p in prims] == ["PPolyline"] and prims[0].stroke == BRAND_PALETTE.arrow and prims[0].width == style.BRACKET_WIDTH
    cota = bracket_primitives(replace(b, kind=BracketKind.DIMENSION), 1.0)
    assert [type(p).__name__ for p in cota] == ["PPolyline"] * 3 + ["PPolygon"] * 2        # tres trazos y las dos puntas


def test_el_resplandor_apila_nueve_capas_por_trazo_debajo_de_la_forma():
    prims = bracket_primitives(H, 1.0)
    rings = len(style.glow_rings())
    assert len(prims) == rings + 1 and all(isinstance(p, PPolyline) for p in prims)
    widths = [p.width for p in prims[:-1]]
    assert widths == sorted(widths, reverse=True) and prims[-1].stroke == BRAND_PALETTE.arrow and prims[0].stroke == BRAND_PALETTE.glow


def test_color_y_grosor_propios_y_escala():
    b = replace(H, glow=False, color="#123456", width=6.0)
    p = bracket_primitives(b, 2.0)[0]
    assert p.stroke == "#123456" and p.width == 12.0


def test_el_texto_del_pico_suma_su_etiqueta_y_el_icono_su_dibujo():
    con_texto = bracket_primitives(replace(H, glow=False, tip=TipContent.TEXT, label="Total"), 1.0)
    assert any(isinstance(p, PText) and p.text == "Total" for p in con_texto) and any(isinstance(p, PRect) for p in con_texto)
    con_icono = bracket_primitives(replace(H, glow=False, tip=TipContent.ICON), 1.0)
    assert len(con_icono) > 1
    assert len(bracket_primitives(replace(H, glow=False), 1.0)) == 1


def test_las_puntas_de_la_cota_miran_hacia_afuera_en_cada_extremo():
    b = replace(H, glow=False, kind=BracketKind.DIMENSION, depth=30.0)
    heads = [p for p in bracket_primitives(b, 1.0) if isinstance(p, PPolygon)]
    left, right = heads
    assert left.points[0] == pytest.approx((100.0, 230.0)) and left.points[1][0] > 100.0          # la punta toca el extremo y la base va hacia adentro
    assert right.points[0] == pytest.approx((400.0, 230.0)) and right.points[1][0] < 400.0


def test_la_caja_dibujada_incluye_el_texto_del_pico_y_el_margen_necesario_lo_cuenta():
    doc = AnnotationDoc(image_path=None, image_size=(800, 600), items=[], style_scale=1.0)
    sin = Bracket("b", (100.0, 560.0), (400.0, 560.0), depth=30.0, glow=False)
    con = replace(sin, tip=TipContent.TEXT, label="Total")
    assert item_box(doc, con, 1.0).bottom > item_box(doc, sin, 1.0).bottom + 10
    doc2 = AnnotationDoc(image_path=None, image_size=(800, 600), items=[con], style_scale=1.0)
    assert required_padding(doc2) > 0                                                         # el texto se sale por abajo


# --- seleccion y edicion ----------------------------------------------------------------------------------------------


def test_se_selecciona_sobre_el_trazo_sobre_el_texto_y_sobre_el_icono_pero_no_en_el_hueco():
    b = replace(H, depth=40.0)
    assert edit.hit_item(b, (100.0, 200.0), 4.0, 1.0)
    assert not edit.hit_item(b, (250.0, 215.0), 4.0, 1.0)                              # entre el tramo y el pico: hueco
    con_texto = replace(b, tip=TipContent.TEXT, label="Total")
    box = label_box(bracket_tip_item(con_texto, 1.0), 1.0)
    assert edit.hit_item(con_texto, box.center, 4.0, 1.0)
    con_icono = replace(b, tip=TipContent.ICON)
    assert edit.hit_item(con_icono, bracket_tip_item(con_icono, 1.0).center, 4.0, 1.0)
    assert not edit.hit_item(replace(b, tip=TipContent.TEXT, label="Total"), (50.0, 50.0), 4.0, 1.0)


def test_el_trazo_grueso_se_alcanza_con_su_mitad_de_grosor():
    b = replace(H, depth=40.0, width=20.0)
    assert edit.hit_item(b, (92.0, 200.0), 2.0, 1.0) and not edit.hit_item(replace(b, width=2.0), (92.0, 200.0), 2.0, 1.0)   # a 8 px del extremo


def test_tiene_asas_en_los_extremos_y_en_el_pico():
    handles = edit.item_handles(replace(H, depth=40.0))
    assert set(handles) == {edit.Handle.START, edit.Handle.END, edit.Handle.MID}
    assert handles[edit.Handle.MID] == pytest.approx((250.0, 240.0))
    assert set(edit.item_handles(Bracket("b", (5.0, 5.0), (5.0, 5.0)))) == {edit.Handle.START, edit.Handle.END}


def test_arrastrar_el_pico_cambia_la_profundidad_y_el_lado():
    assert edit.resize_item(H, edit.Handle.MID, (250.0, 245.0)).depth == pytest.approx(45.0)
    arriba = edit.resize_item(H, edit.Handle.MID, (250.0, 150.0))
    assert arriba.depth == pytest.approx(50.0) and arriba.flip is True
    de_vuelta = edit.resize_item(arriba, edit.Handle.MID, (250.0, 260.0))
    assert de_vuelta.flip is False and de_vuelta.depth == pytest.approx(60.0)


def test_la_profundidad_arrastrada_se_acota():
    assert edit.resize_item(H, edit.Handle.MID, (250.0, 200.5)).depth == style.MIN_BRACKET_DEPTH
    assert edit.resize_item(H, edit.Handle.MID, (250.0, 9000.0)).depth == style.MAX_BRACKET_DEPTH


@pytest.mark.parametrize("flip", [False, True])
@pytest.mark.parametrize("end", [(400.0, 200.0), (150.0, 420.0)])
def test_soltar_el_asa_donde_esta_deja_la_misma_forma(flip, end):
    b = Bracket("b", (100.0, 200.0), end, depth=33.0, flip=flip)
    out = edit.resize_item(b, edit.Handle.MID, edit.item_handles(b)[edit.Handle.MID])
    assert out.depth == pytest.approx(33.0) and out.flip is flip


def test_mover_un_extremo_o_toda_la_llave_conserva_forma_y_lado():
    b = replace(H, depth=33.0, flip=True)
    assert edit.resize_item(b, edit.Handle.END, (500.0, 260.0)).end == (500.0, 260.0)
    moved = edit.move_item(b, 15.0, -5.0)
    assert (moved.start, moved.end, moved.depth, moved.flip) == ((115.0, 195.0), (415.0, 195.0), 33.0, True)


def test_la_caja_de_seleccion_incluye_la_forma_y_el_texto():
    b = replace(H, depth=40.0, tip=TipContent.TEXT, label="Total")
    box = edit.selection_rect(b, 1.0)
    label = label_box(bracket_tip_item(b, 1.0), 1.0)
    assert box.x <= 100.0 and box.right >= 400.0 and box.bottom >= label.bottom and box.y <= 200.0
    assert edit.selection_rect(Bracket("b", (5.0, 6.0), (5.0, 6.0)), 1.0).w == 0.0


# --- proyecto ---------------------------------------------------------------------------------------------------------


def test_se_guarda_y_se_recupera_todo():
    b = Bracket("b", (1.0, 2.0), (90.0, 40.0), kind=BracketKind.DIMENSION, depth=44.0, flip=True, color="#112233", width=7.0,
                glow=False, glow_color="#445566", glow_strength=1.5, glow_size=0.7, tip=TipContent.TEXT, label="Ancho",
                label_preset="alerta", label_size=30.0, tip_icon=IconKind.STAR, tip_icon_size=22.0)
    data = item_to_dict(b)
    assert data["type"] == "bracket" and data["kind"] == "dimension" and data["tip"] == "text"
    assert item_from_dict(data) == b


def test_un_proyecto_con_lo_minimo_abre_con_los_valores_de_fabrica():
    b = item_from_dict({"type": "bracket", "id": "b1", "start": [1, 2], "end": [3, 4]})
    assert (b.kind, b.tip, b.depth, b.flip, b.glow, b.label, b.label_preset) == (
        BracketKind.BRACE, TipContent.NONE, 28.0, False, True, "", "nota")
    assert (b.width, b.label_size, b.tip_icon, b.tip_icon_size) == (
        style.BRACKET_WIDTH, style.BRACKET_LABEL_SIZE, IconKind.CHECK, style.DEFAULT_TIP_ICON_SIZE)


def test_valores_invalidos_caen_a_los_de_fabrica():
    malo = {"type": "bracket", "id": "b1", "start": [1, 2], "end": [3, 4], "kind": "raro", "depth": 99999, "flip": "si",
            "width": -3, "tip": 7, "label": "x" * 500, "label_preset": "zzz", "label_size": 0, "tip_icon": "nada", "tip_icon_size": 1e9,
            "glow_strength": "mucha"}
    b = item_from_dict(malo)
    assert (b.kind, b.depth, b.flip, b.width, b.tip, b.label, b.label_preset, b.label_size, b.tip_icon) == (
        BracketKind.BRACE, 28.0, False, style.BRACKET_WIDTH, TipContent.NONE, "", "nota", style.BRACKET_LABEL_SIZE, IconKind.CHECK)
    assert b.tip_icon_size == style.DEFAULT_TIP_ICON_SIZE


def test_la_etiqueta_apagada_conserva_su_texto_en_el_proyecto():
    b = replace(H, tip=TipContent.NONE, label="Total")
    assert item_from_dict(item_to_dict(b)).label == "Total"


# --- Qt contra resvg ----------------------------------------------------------------------------------------------------


def _export(tmp_path, item, size=(500, 400)):
    Image.new("RGB", size, (255, 255, 255)).save(tmp_path / "c.png")
    export_png(AnnotationDoc(tmp_path / "c.png", size, [item], style_scale=1.0), tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def test_la_exportacion_dibuja_la_forma_el_texto_y_el_resto_queda_intacto(tmp_path):
    b = Bracket("b", (100.0, 150.0), (400.0, 150.0), depth=40.0, glow=False, color="#C02060", tip=TipContent.TEXT, label="Total",
                label_preset="alerta2")
    img = _export(tmp_path, b)
    assert img.getpixel((100, 150)) != (255, 255, 255) or img.getpixel((101, 152)) != (255, 255, 255)
    assert img.getpixel((250, 20)) == (255, 255, 255) and img.getpixel((10, 350)) == (255, 255, 255)
    box = label_box(bracket_tip_item(b, 1.0), 1.0)
    cx, cy = int(box.x + 6), int(box.center[1])
    mixed = tuple(round(0.92 * c + 0.08 * 255) for c in (0xD3, 0x2F, 0x2F))                  # el fondo de "alerta2" al 92 % sobre blanco
    assert all(abs(a - b) <= 3 for a, b in zip(img.getpixel((cx, cy)), mixed))


def test_el_pintor_de_qt_dibuja_la_llave_igual_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    for kind in (BracketKind.BRACE, BracketKind.SQUARE, BracketKind.PAREN, BracketKind.DIMENSION):
        b = Bracket("b", (80.0, 120.0), (420.0, 260.0), kind=kind, depth=50.0, color="#2060C0", width=6.0)
        resvg = _export(tmp_path, b)
        img = QImage(500, 400, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        paint_primitives(painter, bracket_primitives(b, 1.0))
        painter.end()
        diffs = total = 0
        for x in range(40, 460, 6):
            for y in range(60, 340, 6):
                q, r = QColor(img.pixel(x, y)), resvg.getpixel((x, y))
                total += 1
                diffs += max(abs(q.red() - r[0]), abs(q.green() - r[1]), abs(q.blue() - r[2])) > 14
        assert diffs / total < 0.02, (kind, diffs, total)


# --- controlador y panel --------------------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.annotate.controller import STICKY_TOOLS, Tool
from ui.annotate.panel import _PAGE_BRACKET, BRACKET_TITLES
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1400, 850)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _drag(canvas, a, b):
    for kind, pt, buttons, button in ((QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton),
                                      (QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton),
                                      (QEvent.MouseButtonRelease, b, Qt.NoButton, Qt.LeftButton)):
        pos = canvas.image_to_view(pt)
        QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def _brackets(tab):
    return [i for i in tab.doc.items if isinstance(i, Bracket)]


def _draw(tab, a=(100.0, 100.0), b=(400.0, 100.0)):
    tab.tool_buttons[Tool.BRACKET].click()
    _drag(tab.canvas, a, b)
    return tab.controller.selected_item()


def test_la_herramienta_llave_existe_se_repite_y_su_boton_tiene_texto(tab):
    assert Tool.BRACKET in STICKY_TOOLS and tab.tool_buttons[Tool.BRACKET].text() == "Llave"
    assert tab.tool_buttons[Tool.BRACKET].isEnabled()


def test_dibujar_crea_una_llave_con_profundidad_proporcional_y_un_solo_paso(tab):
    steps = tab.controller.stack.count()
    b = _draw(tab)
    assert isinstance(b, Bracket) and b.kind is BracketKind.BRACE and not b.flip and b.tip is TipContent.NONE
    assert b.start == pytest.approx((100.0, 100.0)) and b.end == pytest.approx((400.0, 100.0))
    assert b.depth == pytest.approx(bg.default_depth(b.start, b.end))
    assert tab.controller.stack.count() == steps + 1 and tab.controller.tool is Tool.BRACKET     # la herramienta sigue activa
    tab.controller.undo()
    assert not _brackets(tab)


def test_un_arrastre_diminuto_no_deja_nada_y_se_pueden_dibujar_varias(tab):
    tab.tool_buttons[Tool.BRACKET].click()
    _drag(tab.canvas, (200.0, 200.0), (201.0, 201.0))
    assert not _brackets(tab)
    _drag(tab.canvas, (100.0, 100.0), (300.0, 100.0))
    _drag(tab.canvas, (100.0, 300.0), (300.0, 300.0))
    assert len(_brackets(tab)) == 2


def test_el_panel_muestra_la_pagina_de_la_llave_con_su_titulo(tab):
    _draw(tab)
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_BRACKET and p._pages.currentWidget().isAncestorOf(p._br_kind)
    assert p._title.text() == BRACKET_TITLES[BracketKind.BRACE] == "Llave"
    assert [p._br_kind.itemData(i) for i in range(p._br_kind.count())] == ["brace", "square", "paren", "dimension"]
    assert [p._br_tip.itemData(i) for i in range(p._br_tip.count())] == ["none", "text", "icon"]


def test_cambiar_la_forma_la_deja_como_la_de_las_nuevas_y_cambia_el_titulo(tab):
    _draw(tab)
    p = tab.panel
    p._br_kind.setCurrentIndex(p._br_kind.findData("dimension"))
    assert tab.controller.selected_item().kind is BracketKind.DIMENSION and tab.controller.bracket_kind is BracketKind.DIMENSION
    assert p._title.text() == "Cota"
    nueva = _draw(tab, (100.0, 300.0), (350.0, 300.0))
    assert nueva.kind is BracketKind.DIMENSION


def test_las_filas_del_pico_aparecen_segun_el_contenido(tab):
    _draw(tab)
    p = tab.panel
    text_rows = (p._br_label_row, p._br_preset_row, p._br_label_size_row)
    icon_rows = (p._br_icon_row, p._br_icon_size_row)
    assert not any(p._br_form.isRowVisible(r) for r in text_rows + icon_rows)
    p._br_tip.setCurrentIndex(p._br_tip.findData("text"))
    assert all(p._br_form.isRowVisible(r) for r in text_rows) and not any(p._br_form.isRowVisible(r) for r in icon_rows)
    p._br_tip.setCurrentIndex(p._br_tip.findData("icon"))
    assert all(p._br_form.isRowVisible(r) for r in icon_rows) and not any(p._br_form.isRowVisible(r) for r in text_rows)


def test_escribir_o_elegir_un_texto_rapido_lo_aplica_y_apagar_el_pico_lo_conserva(tab):
    _draw(tab)
    p = tab.panel
    p._br_tip.setCurrentIndex(p._br_tip.findData("text"))
    p._br_label.setEditText("Mi texto")
    assert tab.controller.selected_item().label == "Mi texto"
    p._br_label.setCurrentIndex(p._br_label.findText("Error"))
    assert tab.controller.selected_item().label == "Error"
    p._br_tip.setCurrentIndex(p._br_tip.findData("none"))
    b = tab.controller.selected_item()
    assert b.tip is TipContent.NONE and b.label == "Error"                                  # se apaga sin perder el texto
    assert bracket_tip_item(b, 1.0) is None
    p._br_tip.setCurrentIndex(p._br_tip.findData("text"))
    assert bracket_tip_item(tab.controller.selected_item(), 1.0).text == "Error"


def test_los_textos_rapidos_son_los_de_la_lista(tab):
    p = tab.panel
    assert [p._br_label.itemText(i) for i in range(p._br_label.count())] == list(style.BRACKET_QUICK_TEXTS)
    assert {"Total", "Error", "Paso 1"} <= set(style.BRACKET_QUICK_TEXTS)


def test_el_estilo_el_tamano_y_el_icono_del_pico_se_editan_desde_el_panel(tab):
    _draw(tab)
    p = tab.panel
    p._br_tip.setCurrentIndex(p._br_tip.findData("text"))
    p._br_label.setEditText("Total")
    p._br_preset.setCurrentIndex(p._br_preset.findData("exito"))
    p._br_label_size.setValue(30)
    p._br_tip.setCurrentIndex(p._br_tip.findData("icon"))
    p._br_icon.setCurrentIndex(p._br_icon.findData("warning"))
    p._br_icon_size.setValue(24)
    b = tab.controller.selected_item()
    assert (b.label_preset, b.label_size, b.tip_icon, b.tip_icon_size) == ("exito", 30.0, IconKind.WARNING, 24.0)


def test_profundidad_lado_grosor_y_resplandor_desde_el_panel(tab):
    _draw(tab)
    p = tab.panel
    p._br_depth.setValue(55)
    p._br_flip.setChecked(True)
    p._br_width.setValue(8.0)
    p._br_glow.setChecked(False)
    b = tab.controller.selected_item()
    assert (b.depth, b.flip, b.width, b.glow) == (55.0, True, 8.0, False)


def test_restablecer_la_profundidad_vuelve_a_la_proporcional_al_largo(tab):
    b = _draw(tab)
    tab.controller.edit_selected(_merge=False, depth=120.0)
    assert tab.panel._bracket_default_depth() == pytest.approx(bg.default_depth(b.start, b.end))


def test_arrastrar_el_asa_del_pico_en_el_lienzo_cambia_la_profundidad_y_se_deshace(tab):
    b = _draw(tab)
    tab.tool_buttons[Tool.SELECT].click()
    tab.controller.select(b.id)
    tip = bg.tip_point(b)
    _drag(tab.canvas, tip, (tip[0], tip[1] + 40.0))
    moved = tab.controller.selected_item()
    assert moved.depth == pytest.approx(b.depth + 40.0, abs=1.5) and moved.start == b.start and moved.end == b.end
    tab.controller.undo()
    assert tab.controller.selected_item().depth == b.depth


def test_editar_varias_llaves_a_la_vez_cambia_a_todas(tab):
    tab.tool_buttons[Tool.BRACKET].click()
    _drag(tab.canvas, (100.0, 100.0), (300.0, 100.0))
    _drag(tab.canvas, (100.0, 300.0), (300.0, 300.0))
    tab.tool_buttons[Tool.SELECT].click()
    tab.controller.select_many([i.id for i in _brackets(tab)])
    tab.panel._br_flip.setChecked(True)
    assert all(i.flip for i in _brackets(tab))


def test_alinear_y_mover_una_llave_con_las_herramientas_comunes(tab):
    from core.annotate import align as aligning
    b = _draw(tab, (100.0, 100.0), (300.0, 100.0))
    tab.tool_buttons[Tool.SELECT].click()
    tab.controller.select(b.id)
    tab.controller.align_selected(aligning.Align.CENTER_H, to_image=True)
    moved = tab.controller.selected_item()
    assert (moved.start[0] + moved.end[0]) / 2 == pytest.approx(400.0, abs=1.0)
    assert moved.depth == b.depth


def test_el_proyecto_con_llaves_se_guarda_y_se_vuelve_a_abrir(tab):
    from core.annotate.io import load_doc, save_doc, sidecar_path
    b = _draw(tab)
    tab.controller.edit_selected(_merge=False, tip=TipContent.TEXT, label="Total", flip=True)
    save_doc(tab.doc)
    loaded = load_doc(sidecar_path(tab.doc.image_path))
    assert [i for i in loaded.items if isinstance(i, Bracket)] == _brackets(tab)
    assert _brackets(tab)[0].label == "Total" and _brackets(tab)[0].id == b.id
