from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import (
    AnnotationDoc,
    Arrow,
    ArrowSide,
    LensShape,
    Magnifier,
    Marker,
    Rect,
    StepBadge,
)
from core.annotate.palette import BRAND_PALETTE, Palette, is_valid_hex, palette_from_dict, palette_to_dict
from core.annotate.primitives import (
    PCircle,
    PLine,
    PPolygon,
    PRect,
    PText,
    arrow_primitives,
    build_primitives,
    magnifier_primitives,
    marker_primitives,
    step_primitives,
)
from core.annotate.svg import export_png

GREEN, BLUE, PINK = "#00AA00", "#2255DD", "#FF66AA"
MARKER = Marker("m", Rect(100, 100, 200, 50))


def colors(prims, kind, attr):
    return {getattr(p, attr) for p in prims if isinstance(p, kind)}


# --- paleta -------------------------------------------------------------------

def test_la_paleta_por_defecto_es_la_de_marca():
    assert BRAND_PALETTE == Palette(style.RED, style.RED, style.GLOW_GOLD, style.TAN, style.GOLD)


def test_is_valid_hex():
    assert is_valid_hex("#21B868") and is_valid_hex("#abcdef")
    for malo in ("21B868", "#21B86", "#21B8688", "#GGGGGG", "rojo", "", None, 123):
        assert not is_valid_hex(malo)


def test_palette_ida_y_vuelta():
    p = Palette(marker=GREEN, arrow=BLUE, glow=PINK, lens="#111111", step="#222222")
    assert palette_from_dict(palette_to_dict(p)) == p


def test_palette_from_dict_tolera_datos_viejos_o_danados():
    assert palette_from_dict(None) == BRAND_PALETTE
    assert palette_from_dict("no soy un dict") == BRAND_PALETTE
    assert palette_from_dict({}) == BRAND_PALETTE
    # una clave desconocida se ignora; un color invalido cae al de marca SOLO en ese campo
    p = palette_from_dict({"marker": GREEN, "arrow": "rojo", "glow": "#12", "inventada": "#FFFFFF"})
    assert p == Palette(marker=GREEN)


# --- primitivas ---------------------------------------------------------------

def test_sin_paleta_ni_colores_propios_salen_los_de_marca():
    prims = marker_primitives(MARKER, 1.0, ArrowSide.LEFT)
    assert colors(prims, PRect, "stroke") == {style.RED, style.GLOW_GOLD}
    assert prims == marker_primitives(MARKER, 1.0, ArrowSide.LEFT, BRAND_PALETTE)


def test_la_paleta_cambia_recuadro_flecha_y_resplandor_por_separado():
    p = Palette(marker=GREEN, arrow=BLUE, glow=PINK)
    prims = marker_primitives(MARKER, 1.0, ArrowSide.LEFT, p)
    assert colors(prims, PRect, "stroke") == {GREEN, PINK}           # recuadro + anillos del resplandor
    assert BLUE in colors(prims, PLine, "stroke") and PINK in colors(prims, PLine, "stroke")  # flecha + su resplandor
    assert next(x for x in prims if isinstance(x, PPolygon) and x.fill).fill == BLUE            # punta de la flecha
    assert style.RED not in colors(prims, PRect, "stroke") | colors(prims, PLine, "stroke")
    assert style.GLOW_GOLD not in colors(prims, PRect, "stroke") | colors(prims, PLine, "stroke")


def test_el_color_propio_gana_a_la_paleta_y_none_hereda():
    p = Palette(marker=GREEN, arrow=BLUE, glow=PINK)
    propio = replace(MARKER, stroke_color="#FFFF00", arrow_color="#FF0000", glow_color="#00FFFF")
    prims = marker_primitives(propio, 1.0, ArrowSide.LEFT, p)
    assert colors(prims, PRect, "stroke") == {"#FFFF00", "#00FFFF"}
    assert colors(prims, PLine, "stroke") == {"#FF0000", "#00FFFF"}
    parcial = replace(MARKER, stroke_color="#FFFF00")  # solo el recuadro es propio: lo demas hereda
    prims = marker_primitives(parcial, 1.0, ArrowSide.LEFT, p)
    assert colors(prims, PRect, "stroke") == {"#FFFF00", PINK}
    assert BLUE in colors(prims, PLine, "stroke")


def test_marcador_sin_resplandor_no_usa_el_color_del_resplandor():
    prims = marker_primitives(replace(MARKER, glow=False), 1.0, ArrowSide.LEFT, Palette(glow=PINK))
    assert PINK not in colors(prims, PRect, "stroke") | colors(prims, PLine, "stroke")


def test_flecha_suelta_usa_color_de_flecha_y_resplandor():
    a = Arrow("a", (0.0, 0.0), (100.0, 0.0))
    prims = arrow_primitives(a, 1.0, Palette(arrow=BLUE, glow=PINK))
    assert colors(prims, PLine, "stroke") == {BLUE, PINK}
    propia = arrow_primitives(replace(a, color=GREEN, glow_color="#000000"), 1.0, Palette(arrow=BLUE, glow=PINK))
    assert colors(propia, PLine, "stroke") == {GREEN, "#000000"}


def test_paso_numerado_usa_el_color_para_el_circulo_y_el_numero():
    s = StepBadge("s", (50.0, 50.0), 3)
    prims = step_primitives(s, 1.0, Palette(step=PINK))
    assert next(p for p in prims if isinstance(p, PCircle)).stroke == PINK
    assert next(p for p in prims if isinstance(p, PText)).color == PINK
    assert next(p for p in step_primitives(replace(s, color=GREEN), 1.0, Palette(step=PINK)) if isinstance(p, PText)).color == GREEN


def test_el_marco_de_la_lupa_usa_su_color_pero_el_contorno_navy_no_cambia():
    m = Magnifier("l", Rect(100, 100, 60, 60), (400.0, 300.0), 2.0, LensShape.CIRCLE)
    prims = magnifier_primitives(m, 1.0, Palette(lens=PINK))
    tan_strokes = colors(prims, PCircle, "stroke") | colors(prims, PLine, "stroke")
    assert PINK in tan_strokes and style.TAN not in tan_strokes
    assert style.CARD_FILL in tan_strokes  # el contorno oscuro que da contraste sobre capturas claras es fijo
    propio = magnifier_primitives(replace(m, frame_color=GREEN), 1.0, Palette(lens=PINK))
    assert GREEN in colors(propio, PCircle, "stroke") and PINK not in colors(propio, PCircle, "stroke")


def test_build_primitives_usa_la_paleta_del_documento():
    doc = AnnotationDoc(Path("x.png"), (800, 500), [MARKER, StepBadge("s", (50.0, 50.0), 1)],
                        style_scale=1.0, palette=Palette(marker=GREEN, step=PINK))
    prims = build_primitives(doc)
    assert GREEN in colors(prims, PRect, "stroke") and PINK in colors(prims, PCircle, "stroke")
    assert build_primitives(replace(doc, palette=BRAND_PALETTE)) != prims


# --- proyecto JSON --------------------------------------------------------------

COLORED = [
    Marker("a1", Rect(1, 2, 3, 4), ArrowSide.TOP, True, GREEN, PINK, BLUE),
    Arrow("a2", (1.0, 2.0), (3.0, 4.0), True, GREEN, PINK),
    StepBadge("a3", (5.0, 6.0), 7, BLUE),
    Magnifier("a4", Rect(1, 2, 3, 4), (5.0, 6.0), 3.0, LensShape.ROUNDED, False, PINK),
]


@pytest.mark.parametrize("item", COLORED, ids=lambda i: type(i).__name__)
def test_colores_propios_ida_y_vuelta(item):
    assert item_from_dict(item_to_dict(item)) == item


def test_un_proyecto_viejo_sin_claves_de_color_se_abre_con_none():
    marcador = {"type": "marker", "id": "a1", "rect": [1, 2, 3, 4], "arrow": "auto", "glow": True}
    flecha = {"type": "arrow", "id": "a2", "start": [0, 0], "end": [9, 9], "glow": True}
    paso = {"type": "step", "id": "a3", "center": [5, 5], "number": 1}
    lupa = {"type": "magnifier", "id": "a4", "source": [1, 2, 3, 4], "lens_center": [5, 6], "zoom": 2.0,
            "shape": "circle", "connector": True}
    assert item_from_dict(marcador).stroke_color is None and item_from_dict(flecha).color is None
    assert item_from_dict(paso).color is None and item_from_dict(lupa).frame_color is None


def test_un_color_invalido_en_el_json_se_trata_como_sin_color_propio():
    datos = item_to_dict(replace(COLORED[0], stroke_color=GREEN))
    datos["stroke_color"] = "verde"
    datos["glow_color"] = 42
    item = item_from_dict(datos)
    assert item.stroke_color is None and item.glow_color is None and item.arrow_color == BLUE


def test_la_paleta_del_documento_se_guarda_y_se_carga(tmp_path):
    doc = AnnotationDoc(tmp_path / "cap.png", (100, 100), list(COLORED), palette=Palette(marker=GREEN, glow=PINK))
    loaded = load_doc(save_doc(doc))
    assert loaded.palette == Palette(marker=GREEN, glow=PINK) and loaded.items == COLORED


def test_un_proyecto_sin_paleta_se_abre_con_la_de_marca(tmp_path):
    import json

    path = tmp_path / "viejo.anotar.json"
    path.write_text(json.dumps({"image": "cap.png", "image_size": [10, 10], "items": []}), encoding="utf-8")
    assert load_doc(path).palette == BRAND_PALETTE


# --- exportacion ----------------------------------------------------------------

def test_el_color_elegido_llega_al_png_exportado(tmp_path):
    cap = tmp_path / "cap.png"
    Image.new("RGB", (400, 250), (40, 60, 90)).save(cap)
    marcador = Marker("m", Rect(100, 80, 200, 90), ArrowSide.NONE)
    out = tmp_path / "out.png"

    export_png(AnnotationDoc(cap, (400, 250), [marcador], style_scale=1.0, palette=Palette(marker=GREEN)), out)
    verde = Image.open(out).convert("RGB").getpixel((100, 125))  # borde izquierdo del recuadro
    assert verde == pytest.approx((0, 0xAA, 0), abs=12)

    export_png(AnnotationDoc(cap, (400, 250), [marcador], style_scale=1.0), out)
    rojo = Image.open(out).convert("RGB").getpixel((100, 125))
    assert rojo == pytest.approx((0x62, 0x11, 0x32), abs=12)
