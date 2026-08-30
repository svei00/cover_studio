import base64
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import lens, style
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import AnnotationDoc, LensShape, Magnifier, Marker, Rect, Redaction
from core.annotate.primitives import (
    PCircle,
    PImage,
    PLine,
    PRect,
    build_primitives,
    item_bounds,
    magnifier_primitives,
)
from core.annotate.raster import apply_redactions, lens_crops
from core.annotate.svg import build_svg, export_png, primitive_to_svg, to_svg

SRC = Rect(100, 100, 60, 40)


def mag(shape=LensShape.CIRCLE, **kw):
    return Magnifier(kw.pop("id", "l1"), kw.pop("source", SRC), kw.pop("center", (400.0, 300.0)),
                     kw.pop("zoom", 2.0), shape, kw.pop("connector", True))


# --- primitivas -----------------------------------------------------------

def test_lupa_circular_incluye_imagen_marco_conector_y_origen_punteado():
    m = mag()
    prims = magnifier_primitives(m, 1.0)
    image = next(p for p in prims if isinstance(p, PImage))
    assert image.key == "l1" and image.dest == lens.lens_rect(m) and image.shape == "circle" and image.rx == 0.0
    circles = [p for p in prims if isinstance(p, PCircle)]
    assert any(c.stroke == style.TAN and c.dash for c in circles)               # origen punteado
    frame = [c for c in circles if c.stroke == style.TAN and not c.dash]
    assert len(frame) == 1 and frame[0].width == 4.0 and frame[0].r == lens.lens_rect(m).w / 2
    assert sum(1 for p in prims if isinstance(p, PLine) and p.stroke == style.TAN) == 2  # cono


def test_cada_trazo_tan_lleva_debajo_uno_navy_mas_ancho():
    prims = magnifier_primitives(mag(), 1.0)
    tan_frame = next(p for p in prims if isinstance(p, PCircle) and p.stroke == style.TAN and not p.dash)
    navy = next(p for p in prims if isinstance(p, PCircle) and p.stroke == style.CARD_FILL and p.width == 8.0)
    assert navy.r == tan_frame.r and navy.width > tan_frame.width


def test_lupa_rectangular_usa_rect_redondeado_y_una_recta():
    m = mag(LensShape.ROUNDED)
    prims = magnifier_primitives(m, 1.0)
    image = next(p for p in prims if isinstance(p, PImage))
    assert image.shape == "rounded" and image.rx == pytest.approx(lens.lens_corner_radius(m))
    assert any(isinstance(p, PRect) and p.stroke == style.TAN and p.dash for p in prims)
    assert sum(1 for p in prims if isinstance(p, PLine) and p.stroke == style.TAN) == 1


def test_sin_conector_no_hay_lineas():
    prims = magnifier_primitives(mag(connector=False), 1.0)
    assert not any(isinstance(p, PLine) for p in prims)


def test_la_escala_engrosa_los_trazos_pero_no_el_tamano_del_lente():
    chico, grande = magnifier_primitives(mag(), 1.0), magnifier_primitives(mag(), 2.0)
    assert next(p for p in grande if isinstance(p, PImage)).dest == next(p for p in chico if isinstance(p, PImage)).dest
    f1 = next(p for p in chico if isinstance(p, PCircle) and p.stroke == style.TAN and not p.dash)
    f2 = next(p for p in grande if isinstance(p, PCircle) and p.stroke == style.TAN and not p.dash)
    assert f2.width == 2 * f1.width


def test_build_primitives_y_bounds_de_la_lupa():
    m = mag()
    doc = AnnotationDoc(Path("x.png"), (1000, 600), [m])
    assert any(isinstance(p, PImage) for p in build_primitives(doc))
    assert item_bounds(m, 1.0) == lens.lens_rect(m)


# --- recortes -------------------------------------------------------------

def _split_image(size=(400, 300)) -> Image.Image:
    img = Image.new("RGBA", size, (200, 30, 30, 255))
    img.paste((30, 30, 200, 255), (size[0] // 2, 0, size[0], size[1]))
    return img


def test_lens_crops_mide_lo_que_el_lente_y_solo_toma_lupas():
    img = _split_image()
    items = [Marker("m", Rect(0, 0, 10, 10)), mag(source=Rect(20, 20, 60, 40), shape=LensShape.ROUNDED, zoom=2.5)]
    crops = lens_crops(img, items)
    assert set(crops) == {"l1"} and crops["l1"].size == (150, 100)


def test_el_recorte_es_de_la_zona_de_origen():
    img = _split_image()
    crop = lens_crops(img, [mag(source=Rect(20, 20, 60, 60))])["l1"]
    assert crop.getpixel((10, 10))[:3] == (200, 30, 30)
    crop = lens_crops(img, [mag(source=Rect(300, 100, 60, 60))])["l1"]
    assert crop.getpixel((10, 10))[:3] == (30, 30, 200)


def test_un_dato_pixelado_no_reaparece_dentro_de_la_lupa():
    img = Image.new("RGBA", (200, 200))
    img.putdata([((x * 7) % 256, (y * 11) % 256, (x + y) % 256, 255) for y in range(200) for x in range(200)])
    items = [Redaction("r", Rect(0, 0, 100, 100), block=50), mag(source=Rect(10, 10, 60, 60), zoom=3.0)]
    # el origen (10..70) cruza el limite de bloque en 50; la zona 10..50 queda dentro del primero.
    # En el recorte ampliado x3 eso es 0..120: se examina 10..100, lejos del borde (el remuestreo lo suaviza)
    zona = (10, 10, 100, 100)
    sin_pixelar = lens_crops(img, items)["l1"].crop(zona).getcolors(maxcolors=100000)
    pixelado = lens_crops(apply_redactions(img, items), items)["l1"].crop(zona).getcolors(maxcolors=100000)
    assert sin_pixelar is not None and len(sin_pixelar) > 500
    assert pixelado is not None and len(pixelado) == 1  # un solo color: no queda detalle original


# --- SVG y exportacion ------------------------------------------------------

def _doc(tmp_path, items, size=(400, 300), color=(40, 60, 90)):
    path = tmp_path / "cap.png"
    Image.new("RGB", size, color).save(path)
    return AnnotationDoc(path, size, items)


def test_svg_circular_incrusta_el_recorte_con_clip_circular(tmp_path):
    svg = build_svg(_doc(tmp_path, [mag(source=Rect(20, 20, 60, 60), center=(250.0, 150.0))]))
    assert '<clipPath id="lens-l1"><circle' in svg and 'clip-path="url(#lens-l1)"' in svg
    assert "stroke-dasharray" in svg
    lens_png = re.findall(r'xlink:href="data:image/png;base64,([^"]+)"', svg)[-1]
    assert Image.open(io.BytesIO(base64.b64decode(lens_png))).size == (120, 120)


def test_svg_rectangular_usa_clip_rect_redondeado(tmp_path):
    svg = build_svg(_doc(tmp_path, [mag(LensShape.ROUNDED, source=Rect(20, 20, 60, 40), center=(250.0, 150.0))]))
    assert re.search(r'<clipPath id="lens-l1"><rect [^>]*rx="', svg)


def test_imagen_de_lente_sin_recorte_no_dibuja_ni_truena():
    p = next(p for p in magnifier_primitives(mag(), 1.0) if isinstance(p, PImage))
    assert primitive_to_svg(p, None) == "" and primitive_to_svg(p, {}) == ""


def test_el_lente_exportado_muestra_la_zona_ampliada_con_marco_tan(tmp_path):
    path = tmp_path / "cap.png"
    img = Image.new("RGB", (400, 300), (40, 60, 90))
    img.paste((0, 200, 0), (40, 40, 80, 80))  # cuadro verde = lo que se amplia
    img.save(path)
    m = mag(source=Rect(40, 40, 40, 40), center=(300.0, 200.0), zoom=3.0)  # lente de 120 px de diametro
    doc = AnnotationDoc(path, (400, 300), [m])
    out = tmp_path / "out.png"
    export_png(doc, out)
    result = Image.open(out).convert("RGB")
    cx, cy = 300, 200
    # imagen de 400 px: la escala de trazo se acota a 0.5, asi que el marco tan mide 2 px (r 59..61)
    # sobre un contorno navy de 4 px (r 58..62)
    assert result.getpixel((cx, cy)) == pytest.approx((0, 200, 0), abs=6)       # centro: verde ampliado
    assert result.getpixel((cx + 57, cy)) == pytest.approx((0, 200, 0), abs=6)  # justo dentro del marco
    tan = style.TAN.lstrip("#")
    expected = tuple(int(tan[i:i + 2], 16) for i in (0, 2, 4))
    assert result.getpixel((cx + 59, cy)) == pytest.approx(expected, abs=30)     # marco tan


def test_fuera_del_circulo_no_se_ve_el_recorte(tmp_path):
    path = tmp_path / "cap.png"
    Image.new("RGB", (400, 300), (40, 60, 90)).save(path)
    img = Image.open(path)
    img.paste((0, 200, 0), (0, 0, 400, 300))  # todo verde
    img.save(path)
    m = mag(source=Rect(150, 100, 40, 40), center=(300.0, 200.0), zoom=3.0)
    out = tmp_path / "out.png"
    export_png(AnnotationDoc(path, (400, 300), [m]), out)
    result = Image.open(out).convert("RGB")
    # la esquina del cuadrado del lente (fuera del circulo) conserva el fondo verde, no el recorte
    corner = result.getpixel((300 + 55, 200 + 55))
    assert corner == pytest.approx((0, 200, 0), abs=6)


# --- proyecto JSON -----------------------------------------------------------

@pytest.mark.parametrize("shape", list(LensShape))
def test_magnifier_ida_y_vuelta(shape):
    m = Magnifier("l9", Rect(1, 2, 3, 4), (5.0, 6.0), 3.5, shape, connector=False)
    assert item_from_dict(item_to_dict(m)) == m


def test_proyecto_con_lupa_se_guarda_y_se_carga(tmp_path):
    doc = AnnotationDoc(tmp_path / "cap.png", (100, 100), [mag()])
    assert load_doc(save_doc(doc)).items == doc.items
