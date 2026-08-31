import io
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.bounds import content_bounds, primitive_bounds, required_padding, union_bounds
from core.annotate.model import AnnotationDoc, Arrow, ArrowSide, Marker, Rect, TextLabel
from core.annotate.primitives import PCircle, PImage, PLine, PPolygon, PRect, PText
from core.annotate.svg import export_png, render_bytes


def test_primitive_bounds_incluye_el_grosor_del_trazo():
    assert primitive_bounds(PRect(Rect(10, 10, 20, 20), "#fff", 4.0)) == Rect(8, 8, 24, 24)
    assert primitive_bounds(PRect(Rect(10, 10, 20, 20), None, 4.0, fill="#fff")) == Rect(10, 10, 20, 20)
    assert primitive_bounds(PLine((0.0, 0.0), (10.0, 0.0), "#fff", 4.0)) == Rect(-2, -2, 14, 4)
    assert primitive_bounds(PPolygon(((0.0, 0.0), (10.0, 0.0), (5.0, 8.0)), "#fff", None)) == Rect(0, 0, 10, 8)
    assert primitive_bounds(PCircle((50.0, 50.0), 10.0, None, "#fff", 2.0)) == Rect(39, 39, 22, 22)
    assert primitive_bounds(PImage("l", Rect(1, 2, 3, 4), "circle")) == Rect(1, 2, 3, 4)
    assert primitive_bounds(PText((0.0, 0.0), "x", 10.0, "#fff", False)) is None


def test_union_bounds():
    assert union_bounds([]) is None
    assert union_bounds([Rect(0, 0, 10, 10), Rect(20, 5, 10, 10)]) == Rect(0, 0, 30, 15)


def _doc(items, size=(800, 500), scale=1.0, padding=0):
    return AnnotationDoc(Path("x.png"), size, items, style_scale=scale, padding=padding)


def test_documento_vacio_no_necesita_margen():
    assert content_bounds(_doc([])) is None and required_padding(_doc([])) == 0


def test_un_marcador_en_el_centro_no_necesita_margen():
    assert required_padding(_doc([Marker("m", Rect(300, 200, 100, 50), ArrowSide.NONE)])) == 0


def test_el_margen_necesario_es_lo_que_se_sale_el_resplandor():
    # anillo mas lejano: 19.8 px + medio trazo de 4.5 = 22.05 -> 23 px a escala 1
    pegado = _doc([Marker("m", Rect(0, 200, 100, 50), ArrowSide.NONE)])
    assert required_padding(pegado) == 23
    assert required_padding(_doc([Marker("m", Rect(0, 200, 100, 50), ArrowSide.NONE)], scale=2.0)) == 45


def test_cualquier_borde_cuenta():
    assert required_padding(_doc([Marker("m", Rect(700, 200, 100, 50), ArrowSide.NONE)])) == 23   # derecha
    assert required_padding(_doc([Marker("m", Rect(300, 0, 100, 50), ArrowSide.NONE)])) == 23     # arriba
    assert required_padding(_doc([Marker("m", Rect(300, 450, 100, 50), ArrowSide.NONE)])) == 23   # abajo


def test_una_flecha_que_sale_de_la_imagen_cuenta():
    flecha = Arrow("a", (-30.0, 100.0), (100.0, 100.0))
    assert required_padding(_doc([flecha])) > 30


def test_una_etiqueta_que_se_sale_por_la_derecha_cuenta():
    larga = TextLabel("t", (700.0, 100.0), "Una etiqueta bastante larga", bg=None, border=None)
    assert required_padding(_doc([larga])) > 0


def test_el_margen_necesario_no_depende_del_margen_actual():
    items = [Marker("m", Rect(0, 200, 100, 50), ArrowSide.NONE)]
    assert required_padding(_doc(items, padding=0)) == required_padding(_doc(items, padding=50)) == 23


def test_render_bytes_es_el_mismo_png_que_se_exporta(tmp_path):
    cap = tmp_path / "cap.png"
    Image.new("RGB", (200, 120), (40, 60, 90)).save(cap)
    doc = AnnotationDoc(cap, (200, 120), [Marker("m", Rect(40, 30, 80, 40))])
    out = tmp_path / "out.png"
    export_png(doc, out)
    assert render_bytes(doc) == out.read_bytes()
    assert Image.open(io.BytesIO(render_bytes(doc))).size == (200, 120)


def test_con_el_margen_necesario_el_resplandor_ya_no_se_recorta(tmp_path):
    cap = tmp_path / "cap.png"
    Image.new("RGB", (200, 120), (40, 60, 90)).save(cap)
    doc = AnnotationDoc(cap, (200, 120), [Marker("m", Rect(0, 40, 60, 30), ArrowSide.NONE)], style_scale=1.0)
    doc.padding = required_padding(doc)
    out = tmp_path / "out.png"
    export_png(doc, out)
    result = Image.open(out).convert("RGB")
    assert result.size == (200 + 2 * doc.padding, 120 + 2 * doc.padding)
    navy = tuple(int(style.CARD_FILL.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    # un pixel del margen, pegado al borde izquierdo de la imagen, ya no es el relleno liso: es el resplandor
    glow_px = result.getpixel((doc.padding - 3, doc.padding + 55))
    assert glow_px != navy and glow_px[0] > navy[0] + 20
