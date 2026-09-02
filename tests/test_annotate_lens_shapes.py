import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import edit, lens, style
from core.annotate.bounds import primitive_bounds
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.lens import (
    connector_segments,
    contains_in_lens,
    default_lens_center,
    effective_source,
    lens_corner_radius,
    lens_rect,
    lens_size,
    near_source_border,
)
from core.annotate.model import AnnotationDoc, LensShape, Magnifier, Rect
from core.annotate.primitives import PEllipse, PImage, PLine, PRect, magnifier_primitives
from core.annotate.svg import build_svg, export_png

SRC = Rect(100, 100, 80, 40)  # rectangulo NO cuadrado: la proporcion importa


def mag(shape, **kw):
    return Magnifier(
        kw.pop("id", "l1"), kw.pop("source", SRC), kw.pop("center", (400.0, 300.0)), kw.pop("zoom", 2.0),
        shape, kw.pop("connector", True), kw.pop("frame_color", None), kw.pop("corner", style.DEFAULT_LENS_CORNER),
    )


# --- geometria --------------------------------------------------------------------

def test_el_ovalo_conserva_las_proporciones_arrastradas_y_el_circulo_no():
    assert effective_source(mag(LensShape.ELLIPSE)) == SRC
    cuadrado = effective_source(mag(LensShape.CIRCLE))
    assert cuadrado.w == cuadrado.h == 80


def test_el_lente_ovalado_es_el_origen_por_el_zoom():
    m = mag(LensShape.ELLIPSE, zoom=2.5, center=(500.0, 400.0))
    assert lens_size(m) == (200.0, 100.0)
    assert lens_rect(m).center == (500.0, 400.0)


def test_contiene_un_punto_segun_el_ovalo_y_no_la_caja():
    m = mag(LensShape.ELLIPSE)  # lente 160 x 80 centrado en (400, 300): semiejes 80 y 40
    assert contains_in_lens(m, (400.0, 300.0))
    assert contains_in_lens(m, (479.0, 300.0)) and contains_in_lens(m, (400.0, 339.0))
    assert not contains_in_lens(m, (475.0, 335.0))   # dentro de la caja, fuera del ovalo
    assert contains_in_lens(mag(LensShape.ROUNDED), (475.0, 335.0))  # el rectangulo si la contiene


def test_borde_del_origen_ovalado():
    m = mag(LensShape.ELLIPSE)  # origen: centro (140, 120), semiejes 40 y 20
    assert near_source_border(m, (180.0, 120.0), 4)      # punta derecha
    assert near_source_border(m, (140.0, 140.0), 4)      # punta de abajo
    assert not near_source_border(m, (140.0, 120.0), 4)  # el centro queda libre
    assert not near_source_border(m, (300.0, 300.0), 4)


def test_conector_ovalado_une_los_bordes_de_ambos_ovalos_sobre_la_linea_de_los_centros():
    m = mag(LensShape.ELLIPSE)
    [(p1, p2)] = connector_segments(m)
    src, box = effective_source(m), lens_rect(m)
    for (px, py), rect in ((p1, src), (p2, box)):
        cx, cy = rect.center
        assert math.hypot((px - cx) / (rect.w / 2), (py - cy) / (rect.h / 2)) == pytest.approx(1.0)
    # los dos puntos estan sobre la recta que une los centros
    (x1, y1), (x2, y2) = src.center, box.center
    cruz = (p1[0] - x1) * (y2 - y1) - (p1[1] - y1) * (x2 - x1)
    assert cruz == pytest.approx(0, abs=1e-6)


def test_conector_ovalado_vacio_si_se_solapan_o_esta_apagado():
    assert connector_segments(mag(LensShape.ELLIPSE, center=SRC.center)) == []
    assert connector_segments(mag(LensShape.ELLIPSE, connector=False)) == []


def test_esquinas_del_lente_rectangular():
    m = mag(LensShape.ROUNDED, zoom=2.0)  # lente 160 x 80: lado menor 80
    assert lens_corner_radius(m) == pytest.approx(80 * 0.12)           # el valor de antes
    assert lens_corner_radius(replace(m, corner=0.0)) == 0.0            # esquinas rectas
    assert lens_corner_radius(replace(m, corner=0.5)) == pytest.approx(40)
    assert lens_corner_radius(replace(m, corner=9.0)) == pytest.approx(40)   # se acota
    assert lens_corner_radius(replace(m, corner=-1.0)) == 0.0


def test_el_valor_por_defecto_de_las_esquinas_no_cambio():
    assert style.DEFAULT_LENS_CORNER == 0.12 == lens.ROUNDED_RADIUS_RATIO


def test_la_colocacion_automatica_funciona_con_el_ovalo():
    c = default_lens_center(SRC, 2.0, LensShape.ELLIPSE, (1000, 600))
    m = mag(LensShape.ELLIPSE, center=c)
    assert not lens_rect(m).intersects(effective_source(m))
    box = lens_rect(m)
    assert box.x >= 0 and box.y >= 0 and box.right <= 1000 and box.bottom <= 600


def test_las_asas_del_origen_ovalado_lo_redimensionan_sin_volverlo_cuadrado():
    m = mag(LensShape.ELLIPSE)
    ancho = edit.resize_item(m, edit.Handle.E, (260.0, 120.0))
    assert effective_source(ancho).w == pytest.approx(160) and effective_source(ancho).h == 40
    assert ancho.zoom == m.zoom and ancho.lens_center == m.lens_center


def test_el_asa_del_lente_cambia_el_zoom_del_ovalo_conservando_su_proporcion():
    m = mag(LensShape.ELLIPSE)
    box = lens_rect(m)
    mas = edit.resize_item(m, edit.Handle.LENS, (box.x + 240.0, box.y + 120.0))
    assert mas.zoom == pytest.approx(3.0)
    nuevo = lens_rect(mas)
    assert nuevo.w / nuevo.h == pytest.approx(box.w / box.h)


def test_seleccionar_un_ovalo_ignora_la_esquina_vacia_de_su_caja():
    m = mag(LensShape.ELLIPSE)
    assert edit.hit_lens_part(m, (400.0, 300.0), 6) == "lens"
    assert edit.hit_lens_part(m, (475.0, 335.0), 6) is None   # esquina de la caja, fuera del ovalo


# --- primitivas -------------------------------------------------------------------

def test_lupa_ovalada_dibuja_ovalos_y_su_imagen_se_recorta_en_ovalo():
    prims = magnifier_primitives(mag(LensShape.ELLIPSE), 1.0)
    image = next(p for p in prims if isinstance(p, PImage))
    assert image.shape == "ellipse" and image.rx == 0.0
    ovalos = [p for p in prims if isinstance(p, PEllipse)]
    assert any(p.stroke == style.TAN and p.dash for p in ovalos)             # origen punteado
    marco = [p for p in ovalos if p.stroke == style.TAN and not p.dash]
    assert len(marco) == 1 and marco[0].width == 4.0 and (marco[0].rx, marco[0].ry) == (80.0, 40.0)
    assert any(p.stroke == style.CARD_FILL and p.width == 8.0 for p in ovalos)   # contorno oscuro de contraste
    assert sum(1 for p in prims if isinstance(p, PLine) and p.stroke == style.TAN) == 1  # conector recto


def test_el_color_del_marco_tambien_aplica_al_ovalo():
    prims = magnifier_primitives(mag(LensShape.ELLIPSE, frame_color="#00AA00"), 1.0)
    assert {p.stroke for p in prims if isinstance(p, PEllipse)} >= {"#00AA00"}
    assert style.TAN not in {p.stroke for p in prims if isinstance(p, PEllipse)}


def test_las_esquinas_llegan_a_la_imagen_y_al_marco_rectangular():
    m = mag(LensShape.ROUNDED, corner=0.25)
    prims = magnifier_primitives(m, 1.0)
    radio = lens_corner_radius(m)
    assert next(p for p in prims if isinstance(p, PImage)).rx == pytest.approx(radio)
    marco = [p for p in prims if isinstance(p, PRect) and p.stroke == style.TAN and not p.dash]
    assert len(marco) == 1 and marco[0].rx == pytest.approx(radio)
    rectas = magnifier_primitives(mag(LensShape.ROUNDED, corner=0.0), 1.0)
    assert next(p for p in rectas if isinstance(p, PImage)).rx == 0.0


def test_primitive_bounds_del_ovalo_incluye_el_grosor():
    assert primitive_bounds(PEllipse((50.0, 40.0), 30.0, 10.0, None, "#fff", 4.0)) == Rect(18, 28, 64, 24)
    assert primitive_bounds(PEllipse((50.0, 40.0), 30.0, 10.0, "#fff", None)) == Rect(20, 30, 60, 20)


# --- SVG y exportacion --------------------------------------------------------------

def _capture(tmp_path):
    cap = tmp_path / "cap.png"
    img = Image.new("RGB", (400, 250), (40, 60, 90))
    img.paste((0, 200, 0), (40, 40, 100, 80))  # bloque verde 60x40: lo que se amplia
    img.save(cap)
    return cap


def test_el_svg_del_ovalo_usa_clip_y_marcos_elipticos(tmp_path):
    cap = _capture(tmp_path)
    doc = AnnotationDoc(cap, (400, 250), [mag(LensShape.ELLIPSE, source=Rect(40, 40, 60, 40), center=(300.0, 150.0))])
    svg = build_svg(doc)
    assert '<clipPath id="lens-l1"><ellipse' in svg and svg.count("<ellipse") >= 4
    assert "stroke-dasharray" in svg


def test_el_lente_ovalado_exportado_recorta_en_ovalo(tmp_path):
    cap = _capture(tmp_path)
    m = mag(LensShape.ELLIPSE, source=Rect(40, 40, 60, 40), center=(300.0, 150.0), zoom=2.0)  # lente 120 x 80
    out = tmp_path / "o.png"
    export_png(AnnotationDoc(cap, (400, 250), [m]), out)
    px = Image.open(out).convert("RGB")
    assert px.getpixel((300, 150)) == pytest.approx((0, 200, 0), abs=6)       # centro: el recorte ampliado
    assert px.getpixel((244, 114)) == pytest.approx((40, 60, 90), abs=6)      # esquina de la caja: fuera del ovalo


@pytest.mark.parametrize(("corner", "esquina_visible"), [(0.0, True), (0.5, False)])
def test_las_esquinas_rectas_o_redondeadas_se_ven_en_el_png(tmp_path, corner, esquina_visible):
    cap = _capture(tmp_path)
    m = mag(LensShape.ROUNDED, source=Rect(40, 40, 60, 40), center=(300.0, 150.0), zoom=2.0, corner=corner)
    out = tmp_path / "r.png"
    export_png(AnnotationDoc(cap, (400, 250), [m]), out)
    esquina = Image.open(out).convert("RGB").getpixel((244, 114))  # 4 px dentro de la esquina de la caja
    assert (esquina == pytest.approx((0, 200, 0), abs=6)) is esquina_visible


# --- proyecto guardado --------------------------------------------------------------

@pytest.mark.parametrize("shape", list(LensShape))
@pytest.mark.parametrize("corner", [0.0, 0.12, 0.5])
def test_forma_y_esquinas_ida_y_vuelta(shape, corner):
    m = mag(shape, corner=corner, frame_color="#112233")
    assert item_from_dict(item_to_dict(m)) == m


def test_un_proyecto_viejo_sin_esquinas_usa_el_valor_de_siempre():
    datos = {"type": "magnifier", "id": "l", "source": [1, 2, 3, 4], "lens_center": [5, 6], "zoom": 2.0,
             "shape": "rounded", "connector": True}
    assert item_from_dict(datos).corner == style.DEFAULT_LENS_CORNER


@pytest.mark.parametrize("malo", [2.0, -0.1, "mucho", None, True, [0.2]])
def test_esquinas_invalidas_en_el_json_usan_el_valor_por_defecto(malo):
    datos = item_to_dict(mag(LensShape.ROUNDED))
    datos["corner"] = malo
    assert item_from_dict(datos).corner == style.DEFAULT_LENS_CORNER


def test_proyecto_con_lupa_ovalada_se_guarda_y_se_carga(tmp_path):
    doc = AnnotationDoc(tmp_path / "cap.png", (100, 100), [mag(LensShape.ELLIPSE, corner=0.3)])
    assert load_doc(save_doc(doc)).items == doc.items


# --- interfaz -------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.annotate.controller import Tool  # noqa: E402
from ui.annotate.tab import AnnotateTab  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    img = Image.new("RGB", (800, 500), (40, 60, 90))
    img.paste((0, 200, 0), (100, 100, 200, 160))
    img.save(tmp_path / "cap.png")
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def mdrag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton)


def draw_lens(tab):
    tab.tool_buttons[Tool.LENS].click()
    mdrag(tab.canvas, (100.0, 100.0), (200.0, 160.0))  # rectangulo de 100 x 60: NO cuadrado
    return tab.doc.items[0]


def test_el_panel_ofrece_las_tres_formas(tab):
    draw_lens(tab)
    combo = tab.panel._lens_shape
    assert [combo.itemText(i) for i in range(combo.count())] == ["Circular", "Ovalada", "Rectangular"]


def test_pasar_a_ovalada_conserva_las_proporciones_que_se_arrastraron(tab):
    inicial = draw_lens(tab)
    assert inicial.shape is LensShape.CIRCLE and effective_source(inicial).w == effective_source(inicial).h
    combo = tab.panel._lens_shape
    combo.setCurrentIndex(combo.findData(LensShape.ELLIPSE.value))
    item = tab.doc.items[0]
    assert item.shape is LensShape.ELLIPSE
    src = effective_source(item)
    assert (src.w, src.h) == pytest.approx((100, 60), abs=1)   # la proporcion arrastrada, no un cuadrado


def test_el_control_de_esquinas_solo_aparece_en_la_forma_rectangular(tab):
    draw_lens(tab)
    p = tab.panel
    visible = lambda: p._lens_form.isRowVisible(p._lens_corner_row)  # noqa: E731
    assert not visible()                                          # circular
    p._lens_shape.setCurrentIndex(p._lens_shape.findData(LensShape.ELLIPSE.value))
    assert not visible()                                          # ovalada
    p._lens_shape.setCurrentIndex(p._lens_shape.findData(LensShape.ROUNDED.value))
    assert visible()                                              # rectangular


def test_las_esquinas_se_editan_desde_el_panel_y_se_deshacen(tab):
    draw_lens(tab)
    p = tab.panel
    p._lens_shape.setCurrentIndex(p._lens_shape.findData(LensShape.ROUNDED.value))
    assert p._lens_corner.value() == 12                  # el valor de siempre
    p._lens_corner.setValue(0)
    assert tab.doc.items[0].corner == 0.0
    p._lens_corner.setValue(50)
    assert tab.doc.items[0].corner == 0.5
    tab.controller.undo()  # 0 y 50 son el MISMO campo: se fusionan; vuelve a antes de tocar las esquinas
    assert tab.doc.items[0].corner == 0.12 and tab.doc.items[0].shape is LensShape.ROUNDED


def test_cambiar_a_ovalada_recoloca_el_lente_si_quedaria_pegado(tab):
    draw_lens(tab)
    p = tab.panel
    p._lens_zoom.setValue(3.0)
    p._lens_shape.setCurrentIndex(p._lens_shape.findData(LensShape.ELLIPSE.value))
    item = tab.doc.items[0]
    assert not lens.is_crowded(item)


def _pixel(tab, image_pt):
    img = tab.canvas.grab().toImage()
    v = tab.canvas.image_to_view(image_pt)
    return QColor(img.pixel(int(v.x()), int(v.y())))


def test_en_pantalla_el_ovalo_recorta_su_contenido(tab):
    draw_lens(tab)
    p = tab.panel
    p._lens_shape.setCurrentIndex(p._lens_shape.findData(LensShape.ELLIPSE.value))
    tab.controller.select(None)
    box = lens_rect(tab.doc.items[0])
    centro = _pixel(tab, box.center)
    esquina = _pixel(tab, (box.x + 6, box.y + 6))
    assert centro.green() > 150 and centro.red() < 60                   # el recorte verde ampliado
    assert not (esquina.green() > 150 and esquina.red() < 60)           # fuera del ovalo no se pinta el recorte


def test_arrastrar_el_cuerpo_de_un_ovalo_lo_mueve_pero_su_esquina_vacia_no(tab):
    draw_lens(tab)
    tab.panel._lens_shape.setCurrentIndex(tab.panel._lens_shape.findData(LensShape.ELLIPSE.value))
    box = lens_rect(tab.doc.items[0])
    centro_antes = tab.doc.items[0].lens_center
    mdrag(tab.canvas, (box.x + 4, box.y + 4), (box.x + 54, box.y + 54))   # esquina vacia de la caja
    assert tab.doc.items[0].lens_center == centro_antes
    mdrag(tab.canvas, box.center, (box.center[0] + 50, box.center[1] + 30))
    assert tab.doc.items[0].lens_center != centro_antes
