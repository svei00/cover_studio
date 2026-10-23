"""Flecha dinamica (estilo ShareX): cuerpo conico, punta grande y solida, curva con asa y sombra suave. Todo es opcional: una flecha
con los valores por defecto del modelo es la de siempre."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PIL import Image

from core.annotate import edit, style
from core.annotate.bounds import item_box
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Arrow, ArrowBody, ConnectorRoute, HeadStyle, LineStyle
from core.annotate.primitives import (
    PCircle,
    PLine,
    PPath,
    PPolygon,
    arrow_path,
    arrow_primitives,
    curve_apex,
    curve_control,
    curve_points,
    tapered_outline,
)
from core.annotate.svg import export_png

A = Arrow("a", (100.0, 200.0), (400.0, 200.0))
BLACK = "#000000"


def _kinds(prims):
    return [type(p).__name__ for p in prims]


# --- por defecto es la de siempre -----------------------------------------------------------------------------


def test_los_valores_por_defecto_del_modelo_son_los_de_siempre():
    assert (A.body, A.head_size, A.shadow, A.shadow_strength) == (ArrowBody.UNIFORM, 1.0, False, 1.0)
    assert A.route is ConnectorRoute.STRAIGHT
    assert _kinds(arrow_primitives(A, 1.0)) == ["PLine", "PLine", "PPolygon", "PPolygon"]
    assert not any(getattr(p, "stroke", None) == BLACK or getattr(p, "fill", None) == BLACK for p in arrow_primitives(A, 1.0))


# --- curva ----------------------------------------------------------------------------------------------------


def test_la_curva_empieza_y_termina_en_los_extremos_y_pasa_por_el_apice():
    pts = curve_points(A.start, A.end, 0.5)
    assert pts[0] == pytest.approx(A.start) and pts[-1] == pytest.approx(A.end)
    mid = pts[len(pts) // 2]
    assert mid == pytest.approx(curve_apex(A.start, A.end, 0.5))
    assert mid[1] == pytest.approx(200.0 + 0.5 * 300 / 2)                          # el desvio del apice es bend * largo / 2


def test_el_signo_de_la_curvatura_elige_el_lado():
    up = curve_apex(A.start, A.end, -0.4)
    down = curve_apex(A.start, A.end, 0.4)
    assert up[1] < 200.0 < down[1] and up[0] == pytest.approx(down[0])


def test_curvatura_cero_o_extremos_iguales_es_recta():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.0)
    assert arrow_path(curva) == [A.start, A.end]
    assert arrow_path(replace(A, route=ConnectorRoute.CURVE, end=A.start)) == [A.start, A.start]


def test_la_curva_se_aplana_en_mas_puntos_cuanto_mas_larga():
    assert len(curve_points((0, 0), (40, 0), 0.3)) == 13                               # minimo: 12 tramos
    assert 12 < len(curve_points((0, 0), (200, 0), 0.3)) < len(curve_points((0, 0), (390, 0), 0.3)) <= 81


def test_la_flecha_curva_se_dibuja_con_un_trazo_y_la_punta_sigue_la_tangente():
    curva = Arrow("c", (100.0, 300.0), (400.0, 300.0), route=ConnectorRoute.CURVE, curve_bend=0.5, glow=False)
    prims = arrow_primitives(curva, 1.0)
    assert _kinds(prims) == ["PPath", "PPolygon"]
    punta = prims[1]
    assert punta.points[0] == pytest.approx((400.0, 300.0))
    # la curva llega al extremo desde arriba-izquierda/abajo: la base de la punta NO esta en la misma horizontal que la punta
    assert abs(punta.points[1][1] - 300.0) > 1.0 or abs(punta.points[2][1] - 300.0) > 1.0
    cx, cy = curve_control(curva.start, curva.end, 0.5)
    ux, uy = curva.end[0] - cx, curva.end[1] - cy                                      # tangente al final = end - control
    bx, by = (punta.points[1][0] + punta.points[2][0]) / 2, (punta.points[1][1] + punta.points[2][1]) / 2
    along = (punta.points[0][0] - bx, punta.points[0][1] - by)
    cos = (ux * along[0] + uy * along[1]) / (math.hypot(ux, uy) * math.hypot(*along))
    assert cos > 0.99


def test_la_seleccion_sigue_la_curva_y_no_la_cuerda():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.8)
    apex = curve_apex(curva.start, curva.end, 0.8)
    assert edit.hit_item(curva, apex, 6.0, 1.0)
    assert not edit.hit_item(curva, (250.0, 200.0), 6.0, 1.0)                           # en la cuerda recta, lejos del arco
    box = edit.selection_rect(curva, 1.0)
    assert box.bottom >= apex[1] - 1e-6 and box.y <= 200.0 + 1e-6                       # la caja incluye el arco


# --- asa de la curva ------------------------------------------------------------------------------------------


def test_la_curva_tiene_asa_en_el_apice_y_la_recta_no():
    assert Handle_MID not in edit.item_handles(A)
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.5)
    handles = edit.item_handles(curva)
    assert set(handles) == {edit.Handle.START, edit.Handle.END, edit.Handle.MID}
    assert handles[edit.Handle.MID] == pytest.approx(curve_apex(curva.start, curva.end, 0.5))


Handle_MID = edit.Handle.MID


@pytest.mark.parametrize("bend", [-0.9, -0.3, 0.2, 0.6, 1.0])
def test_arrastrar_el_asa_a_su_posicion_deja_la_misma_curvatura(bend):
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=bend)
    handle = edit.curve_middle_handle(curva)
    assert edit.resize_item(curva, edit.Handle.MID, handle).curve_bend == pytest.approx(bend, abs=1e-9)


def test_arrastrar_el_asa_cambia_la_curvatura_y_el_signo():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.2)
    assert edit.resize_item(curva, edit.Handle.MID, (250.0, 200.0 + 75.0)).curve_bend == pytest.approx(0.5)
    assert edit.resize_item(curva, edit.Handle.MID, (250.0, 200.0 - 75.0)).curve_bend == pytest.approx(-0.5)


def test_la_curvatura_se_acota_y_se_pega_a_cero():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.2)
    assert edit.resize_item(curva, edit.Handle.MID, (250.0, 5000.0)).curve_bend == style.MAX_CURVE_BEND
    assert edit.resize_item(curva, edit.Handle.MID, (250.0, -5000.0)).curve_bend == -style.MAX_CURVE_BEND
    assert edit.resize_item(curva, edit.Handle.MID, (250.0, 203.0)).curve_bend == 0.0   # casi recta: se queda recta


def test_mover_la_flecha_curva_conserva_la_curvatura_relativa():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.4)
    moved = edit.move_item(curva, 30.0, -10.0)
    assert moved.curve_bend == 0.4 and moved.start == (130.0, 190.0)
    assert curve_apex(moved.start, moved.end, 0.4) == pytest.approx(
        (curve_apex(curva.start, curva.end, 0.4)[0] + 30.0, curve_apex(curva.start, curva.end, 0.4)[1] - 10.0))


def test_mover_un_extremo_de_la_curva_la_reacomoda_sin_perder_su_forma():
    curva = replace(A, route=ConnectorRoute.CURVE, curve_bend=0.4)
    longer = edit.resize_item(curva, edit.Handle.END, (700.0, 200.0))
    assert longer.curve_bend == 0.4                                                   # la curvatura es proporcional al largo
    assert curve_apex(longer.start, longer.end, 0.4)[1] > curve_apex(curva.start, curva.end, 0.4)[1]


# --- cuerpo conico --------------------------------------------------------------------------------------------


def test_el_contorno_conico_va_de_delgado_a_grueso():
    out = tapered_outline([(0.0, 0.0), (100.0, 0.0)], 10.0)
    r = style.ARROW_TAIL_RATIO
    assert set(out) == {(0.0, 5 * r), (0.0, -5 * r), (100.0, 5.0), (100.0, -5.0)}
    assert len(out) == 4


def test_el_contorno_conico_crece_a_lo_largo_de_un_camino_largo():
    route = [(float(x), 0.0) for x in range(0, 101, 10)]
    out = tapered_outline(route, 10.0)
    left = out[:len(route)]
    widths = [abs(y) for _x, y in left]
    assert widths == sorted(widths) and widths[0] == pytest.approx(5.0 * style.ARROW_TAIL_RATIO) and widths[-1] == pytest.approx(5.0)


def test_el_contorno_conico_en_un_codo_no_se_afina_ni_se_rompe():
    out = tapered_outline([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], 12.0)
    assert len(out) == 6 and all(math.isfinite(v) for p in out for v in p)
    xs, ys = [p[0] for p in out], [p[1] for p in out]
    assert min(xs) >= -1 and max(xs) <= 100 + 12 * 1.1 and min(ys) >= -12 * 1.1 and max(ys) <= 100 + 1


def test_el_contorno_conico_de_una_ruta_degenerada_es_vacio():
    assert tapered_outline([(5.0, 5.0), (5.0, 5.0)], 10.0) == () and tapered_outline([(1.0, 1.0)], 10.0) == ()


def test_la_flecha_conica_dibuja_un_poligono_en_vez_de_una_linea_y_no_lleva_rayas():
    conica = replace(A, body=ArrowBody.TAPERED, width=8.0, glow=False, line_style=LineStyle.DASHED)
    prims = arrow_primitives(conica, 1.0)
    assert _kinds(prims) == ["PPolygon", "PPolygon"]
    assert len(prims[0].points) == 4 and prims[0].fill is not None and prims[0].stroke is None


def test_el_resplandor_de_una_flecha_conica_es_el_contorno_ensanchado():
    prims = arrow_primitives(replace(A, body=ArrowBody.TAPERED, width=8.0), 1.0)
    assert _kinds(prims) == ["PPolygon"] * 4
    assert prims[0].fill is None and prims[0].stroke is not None and prims[0].width > 0          # halo del cuerpo
    assert prims[1].fill is not None                                                              # cuerpo


def test_el_cuerpo_conico_tambien_sigue_un_codo_y_una_curva():
    for route in (ConnectorRoute.ELBOW, ConnectorRoute.CURVE):
        a = Arrow("a", (100.0, 100.0), (300.0, 220.0), route=route, body=ArrowBody.TAPERED, width=8.0, glow=False)
        prims = arrow_primitives(a, 1.0)
        assert _kinds(prims) == ["PPolygon", "PPolygon"] and len(prims[0].points) >= 6


# --- punta grande ---------------------------------------------------------------------------------------------


def _head(a):
    return [p for p in arrow_primitives(replace(a, glow=False), 1.0) if isinstance(p, PPolygon) and len(p.points) == 3][-1]


def test_el_tamano_de_la_punta_escala_la_punta():
    small, big = _head(A), _head(replace(A, head_size=2.0))
    width = lambda h: abs(h.points[1][1] - h.points[2][1])
    assert width(big) == pytest.approx(2 * width(small))
    assert big.points[0] == small.points[0] == pytest.approx((400.0, 200.0))             # la punta sigue en el extremo


def test_la_punta_sigue_al_grosor_y_al_tamano_a_la_vez():
    assert _head(replace(A, width=10.0)).points[1][1] != _head(A).points[1][1]
    h = _head(replace(A, width=10.0, head_size=1.5))
    base = _head(replace(A, width=10.0))
    assert abs(h.points[1][1] - h.points[2][1]) == pytest.approx(1.5 * abs(base.points[1][1] - base.points[2][1]))


# --- sombra ---------------------------------------------------------------------------------------------------


def test_la_sombra_va_primero_en_negro_y_desplazada_hacia_abajo():
    con = arrow_primitives(replace(A, shadow=True, glow=False), 1.0)
    sin = arrow_primitives(replace(A, glow=False), 1.0)
    assert len(con) == len(sin) + 14                                                    # (6 capas + nucleo) x (cuerpo + punta)
    shadow = con[:14]
    assert all(_color(p) == BLACK for p in shadow) and con[14:] == sin
    body_layers = [p for p in shadow if isinstance(p, PLine)]
    assert all(p.a[1] == pytest.approx(200.0 + style.ARROW_SHADOW_DY) for p in body_layers)


def _color(p):
    return getattr(p, "stroke", None) if isinstance(p, (PLine, PPath)) else (p.stroke or p.fill)


def test_la_sombra_se_apila_de_la_capa_mas_ancha_al_nucleo():
    layers = [p for p in arrow_primitives(replace(A, shadow=True, glow=False), 1.0)[:14] if isinstance(p, PLine)]
    widths = [p.width for p in layers]
    assert widths == sorted(widths, reverse=True) and widths[-1] == 5.0                  # el ultimo es el nucleo (el grosor del cuerpo)
    assert layers[-1].opacity == pytest.approx(style.arrow_shadow_core(1.0))


def test_la_intensidad_de_la_sombra_escala_la_opacidad_con_tope():
    weak = arrow_primitives(replace(A, shadow=True, shadow_strength=0.5, glow=False), 1.0)[:14]
    strong = arrow_primitives(replace(A, shadow=True, shadow_strength=2.0, glow=False), 1.0)[:14]
    alpha = lambda p: p.fill_opacity if isinstance(p, PPolygon) and p.fill else p.opacity      # la opacidad que de verdad se ve
    assert max(alpha(p) for p in weak) < max(alpha(p) for p in strong) <= 1.0
    huge = style.arrow_shadow_rings(50.0)
    assert all(op <= 1.0 for _off, op in huge) and style.arrow_shadow_core(50.0) == 1.0


def test_la_sombra_de_una_flecha_conica_usa_poligonos_con_relleno_translucido():
    prims = arrow_primitives(replace(A, body=ArrowBody.TAPERED, width=8.0, shadow=True, glow=False), 1.0)
    core = [p for p in prims[:14] if isinstance(p, PPolygon) and p.fill == BLACK]
    assert core and all(p.fill_opacity < 1.0 and p.stroke is None for p in core)
    ring = [p for p in prims[:14] if isinstance(p, PPolygon) and p.stroke == BLACK]
    assert ring and all(p.fill is None and p.opacity < 1.0 for p in ring)


def test_la_sombra_de_una_punta_de_punto_es_un_disco_translucido():
    prims = arrow_primitives(replace(A, shadow=True, glow=False, head_end=HeadStyle.DOT), 1.0)
    discos = [p for p in prims[:14] if isinstance(p, PCircle)]
    assert len(discos) == 7 and all(p.stroke == BLACK and p.fill is None and p.width == pytest.approx(2 * p.r) for p in discos)


def test_la_sombra_cuenta_en_la_caja_dibujada_y_en_el_margen_que_hace_falta():
    doc = AnnotationDoc(image_path=None, image_size=(800, 600), items=[], style_scale=1.0)
    plain, shadowed = replace(A, glow=False), replace(A, glow=False, shadow=True)
    box0, box1 = item_box(doc, plain, 1.0), item_box(doc, shadowed, 1.0)
    assert box1.bottom > box0.bottom + style.ARROW_SHADOW_DY and box1.right >= box0.right


def test_una_linea_sin_puntas_tambien_puede_ser_conica_y_tener_sombra():
    linea = Arrow("l", (50.0, 50.0), (350.0, 50.0), head_end=HeadStyle.NONE, body=ArrowBody.TAPERED, width=10.0, shadow=True, glow=False)
    prims = arrow_primitives(linea, 1.0)
    assert len(prims) == 7 + 1 and prims[-1].fill is not None and len(prims[-1].points) == 4


# --- PPolygon con relleno translucido: Qt y el SVG ---------------------------------------------------------------


def test_el_poligono_por_defecto_sigue_siendo_opaco_y_el_svg_no_cambia():
    from core.annotate.svg import primitive_to_svg
    svg = primitive_to_svg(PPolygon(((0.0, 0.0), (10.0, 0.0), (5.0, 8.0)), "#112233", None), {})
    assert "fill-opacity" not in svg
    translucent = primitive_to_svg(PPolygon(((0.0, 0.0), (10.0, 0.0), (5.0, 8.0)), "#112233", None, 0.0, 1.0, 0.4), {})
    assert 'fill-opacity="0.4"' in translucent


def _export(tmp_path, item, size=(500, 400), bg=(255, 255, 255)):
    Image.new("RGB", size, bg).save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", size, [item], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def test_la_sombra_se_ve_en_la_exportacion_debajo_de_la_flecha_y_se_desvanece(tmp_path):
    flecha = Arrow("a", (100.0, 200.0), (400.0, 200.0), body=ArrowBody.TAPERED, width=12.0, shadow=True, glow=False, color="#2060C0")
    img = _export(tmp_path, flecha)
    near = img.getpixel((300, 200 + 7))          # justo debajo del cuerpo: dentro de la sombra
    far = img.getpixel((300, 200 + 60))
    assert sum(near) < 3 * 255 and far == (255, 255, 255)
    assert img.getpixel((300, 200)) == (0x20, 0x60, 0xC0) or sum(abs(a - b) for a, b in zip(img.getpixel((300, 200)), (0x20, 0x60, 0xC0))) < 40


def test_la_flecha_conica_se_exporta_delgada_en_la_cola_y_gruesa_en_la_punta(tmp_path):
    flecha = Arrow("a", (60.0, 200.0), (400.0, 200.0), body=ArrowBody.TAPERED, width=20.0, shadow=False, glow=False,
                   color="#000000", head_end=HeadStyle.NONE)
    img = _export(tmp_path, flecha)

    def thickness(x):
        return sum(1 for y in range(150, 251) if sum(img.getpixel((x, y))) < 300)

    assert thickness(80) < thickness(200) < thickness(390) and thickness(390) >= 17


def test_el_pintor_de_qt_dibuja_la_flecha_dinamica_igual_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    casos = [
        Arrow("a", (80.0, 200.0), (420.0, 200.0), body=ArrowBody.TAPERED, width=14.0, head_size=1.5, shadow=True, color="#2060C0"),
        Arrow("b", (80.0, 300.0), (420.0, 120.0), route=ConnectorRoute.CURVE, curve_bend=0.4, body=ArrowBody.TAPERED, width=12.0,
              shadow=True, color="#C02060"),
        Arrow("c", (80.0, 100.0), (420.0, 100.0), route=ConnectorRoute.CURVE, curve_bend=-0.3, shadow=True, color="#208040"),
    ]
    for caso in casos:
        resvg = _export(tmp_path, caso)
        img = QImage(500, 400, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        paint_primitives(painter, arrow_primitives(caso, 1.0))
        painter.end()
        diffs = 0
        for x in range(60, 440, 7):
            for y in range(60, 340, 7):
                q = QColor(img.pixel(x, y))
                r = resvg.getpixel((x, y))
                if max(abs(q.red() - r[0]), abs(q.green() - r[1]), abs(q.blue() - r[2])) > 12:
                    diffs += 1
        total = len(range(60, 440, 7)) * len(range(60, 340, 7))
        assert diffs / total < 0.02, (caso.id, diffs, total)


# --- proyecto -------------------------------------------------------------------------------------------------


def test_se_guarda_y_se_recupera_todo_lo_nuevo():
    a = Arrow("a", (1.0, 2.0), (30.0, 40.0), route=ConnectorRoute.CURVE, curve_bend=-0.35, body=ArrowBody.TAPERED, head_size=2.2,
              shadow=True, shadow_strength=1.4)
    data = item_to_dict(a)
    assert data["route"] == "curve" and data["body"] == "tapered" and data["shadow"] is True
    assert item_from_dict(data) == a


def test_un_proyecto_viejo_sin_los_campos_nuevos_abre_identico():
    viejo = {"type": "arrow", "id": "a1", "start": [1, 2], "end": [3, 4], "glow": True}
    a = item_from_dict(viejo)
    assert (a.body, a.head_size, a.shadow, a.shadow_strength, a.curve_bend) == (ArrowBody.UNIFORM, 1.0, False, 1.0, style.DEFAULT_CURVE_BEND)
    assert a.route is ConnectorRoute.STRAIGHT and a.width == style.MARKER_STROKE


def test_valores_invalidos_caen_a_los_de_fabrica():
    malo = {"type": "arrow", "id": "a1", "start": [1, 2], "end": [3, 4], "glow": True, "body": "raro", "head_size": 99,
            "curve_bend": 7, "shadow": "si", "shadow_strength": -4, "route": "zigzag"}
    a = item_from_dict(malo)
    assert (a.body, a.head_size, a.shadow, a.shadow_strength) == (ArrowBody.UNIFORM, 1.0, False, 1.0)
    assert a.curve_bend == style.DEFAULT_CURVE_BEND and a.route is ConnectorRoute.STRAIGHT


def test_la_lupa_trata_una_ruta_curva_como_recta():
    """`ConnectorRoute.CURVE` es solo de las flechas: si un archivo la trae en una lupa no debe romper nada."""
    from core.annotate import lens
    from core.annotate.model import Magnifier, Rect
    m = Magnifier("l", Rect(100, 100, 50, 40), (400.0, 300.0), 2.0, connector_route=ConnectorRoute.CURVE)
    assert len(lens.connector_segments(m)) >= 1


# --- controlador y panel ---------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.annotate.controller import Tool
from ui.annotate.panel import ARROW_ROUTE_LABELS, CONNECTOR_ROUTE_LABELS
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
    QApplication.processEvents()
    return t


def _drag(canvas, a, b):
    for kind, pt, buttons, button in ((QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton),
                                      (QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton),
                                      (QEvent.MouseButtonRelease, b, Qt.NoButton, Qt.LeftButton)):
        pos = canvas.image_to_view(pt)
        QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def test_la_herramienta_flecha_crea_la_dinamica_y_linea_la_clasica(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    a = tab.controller.selected_item()
    assert (a.body, a.width, a.head_size, a.shadow) == (ArrowBody.TAPERED, style.DYNAMIC_ARROW_WIDTH, style.DYNAMIC_HEAD_SIZE, True)
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100.0, 300.0), (400.0, 300.0))
    line = tab.controller.selected_item()
    assert (line.body, line.width, line.head_size, line.shadow) == (ArrowBody.UNIFORM, style.MARKER_STROKE, 1.0, False)
    assert line.head_end is HeadStyle.NONE


def test_la_flecha_del_marcador_no_cambia(tab):
    from core.annotate.model import Marker, Rect
    from core.annotate.primitives import build_primitives
    tab.doc.items.append(Marker("m1", Rect(300, 200, 100, 60)))
    tab.controller.changed.emit()
    assert not any(isinstance(p, PPolygon) and p.fill == BLACK for p in build_primitives(tab.doc))


def test_las_rutas_de_la_flecha_incluyen_curvo_y_las_de_la_lupa_no():
    assert ConnectorRoute.CURVE in ARROW_ROUTE_LABELS and ConnectorRoute.CURVE not in CONNECTOR_ROUTE_LABELS
    assert ARROW_ROUTE_LABELS[ConnectorRoute.CURVE] == "Curvo"


def test_el_panel_de_la_flecha_trae_los_controles_nuevos(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    p = tab.panel
    assert [p._arrow_route.itemData(i) for i in range(p._arrow_route.count())] == ["straight", "elbow", "curve"]
    assert [p._arrow_body.itemData(i) for i in range(p._arrow_body.count())] == ["uniform", "tapered"]
    assert p._arrow_body.currentData() == "tapered" and p._arrow_head_size.value() == 150 and p._arrow_shadow.isChecked()
    assert not p._arrow_style.isEnabled()                                                # un cuerpo conico no lleva rayas


def test_la_lupa_solo_ofrece_recto_y_codo(tab):
    p = tab.panel
    assert [p._lens_connector_route.itemData(i) for i in range(p._lens_connector_route.count())] == ["straight", "elbow"]


def test_la_curvatura_solo_se_ve_en_ruta_curva_y_la_intensidad_solo_con_sombra(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    p = tab.panel
    assert not p._arrow_form.isRowVisible(p._arrow_bend_row) and p._arrow_form.isRowVisible(p._arrow_shadow_row)
    p._arrow_route.setCurrentIndex(p._arrow_route.findData("curve"))
    assert p._arrow_form.isRowVisible(p._arrow_bend_row) and tab.controller.selected_item().route is ConnectorRoute.CURVE
    p._arrow_shadow.setChecked(False)
    assert not p._arrow_form.isRowVisible(p._arrow_shadow_row) and tab.controller.selected_item().shadow is False


def test_editar_la_curvatura_y_la_sombra_desde_el_panel(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    p = tab.panel
    p._arrow_route.setCurrentIndex(p._arrow_route.findData("curve"))
    p._arrow_bend.setValue(-60)
    p._arrow_head_size.setValue(250)
    p._arrow_shadow_strength.setValue(160)
    a = tab.controller.selected_item()
    assert (a.curve_bend, a.head_size, a.shadow_strength) == (-0.6, 2.5, 1.6)


def test_cambiar_el_cuerpo_ajusta_grosor_y_punta_en_un_paso_si_eran_de_fabrica(tab):
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    tab.controller.edit_selected(_merge=False, head_end=HeadStyle.ARROW)
    p = tab.panel
    steps = tab.controller.stack.count()
    p._arrow_body.setCurrentIndex(p._arrow_body.findData("tapered"))
    a = tab.controller.selected_item()
    assert (a.body, a.width, a.head_size) == (ArrowBody.TAPERED, style.DYNAMIC_ARROW_WIDTH, style.DYNAMIC_HEAD_SIZE)
    assert tab.controller.stack.count() == steps + 1
    tab.controller.undo()
    a = tab.controller.selected_item()
    assert (a.body, a.width, a.head_size) == (ArrowBody.UNIFORM, style.MARKER_STROKE, 1.0)
    p._arrow_body.setCurrentIndex(p._arrow_body.findData("tapered"))
    p._arrow_body.setCurrentIndex(p._arrow_body.findData("uniform"))
    a = tab.controller.selected_item()
    assert (a.body, a.width, a.head_size) == (ArrowBody.UNIFORM, style.MARKER_STROKE, 1.0)


def test_si_el_grosor_era_personalizado_el_cambio_de_cuerpo_lo_respeta(tab):
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    tab.controller.edit_selected(_merge=False, width=11.0)
    p = tab.panel
    p._arrow_body.setCurrentIndex(p._arrow_body.findData("tapered"))
    a = tab.controller.selected_item()
    assert a.width == 11.0 and a.head_size == style.DYNAMIC_HEAD_SIZE


def test_restablecer_vuelve_al_valor_de_fabrica_del_tipo_de_flecha(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 100.0), (400.0, 160.0))
    tab.controller.edit_selected(_merge=False, width=15.0, head_size=2.5)
    p = tab.panel
    assert p._arrow_factory("width") == style.DYNAMIC_ARROW_WIDTH and p._arrow_factory("head_size") == style.DYNAMIC_HEAD_SIZE
    tab.controller.edit_selected(_merge=False, body=ArrowBody.UNIFORM)
    assert p._arrow_factory("width") == style.MARKER_STROKE and p._arrow_factory("head_size") == 1.0


def test_arrastrar_el_asa_de_la_curva_en_el_lienzo_la_dobla(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100.0, 250.0), (500.0, 250.0))
    tab.tool_buttons[Tool.SELECT].click()                                                   # la herramienta Flecha es pegajosa
    tab.controller.select(tab.controller.selected_id or tab.doc.items[0].id)
    tab.controller.edit_selected(_merge=False, route=ConnectorRoute.CURVE, curve_bend=0.1)
    a = tab.controller.selected_item()
    apex = edit.curve_middle_handle(a)
    _drag(tab.canvas, apex, (apex[0], apex[1] + 80.0))
    b = tab.controller.selected_item()
    assert b.curve_bend > a.curve_bend and b.start == a.start and b.end == a.end
    tab.controller.undo()
    assert tab.controller.selected_item().curve_bend == a.curve_bend
