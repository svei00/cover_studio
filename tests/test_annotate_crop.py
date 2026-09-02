import base64
import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from core.annotate.bounds import items_outside_view, required_padding
from core.annotate.crop import MIN_CROP, full_rect, hit_crop_handle, normalize_crop, resize_crop
from core.annotate.edit import Handle
from core.annotate.io import load_doc, save_doc
from core.annotate.lens import default_lens_center
from core.annotate.model import (
    AnnotationDoc,
    ArrowSide,
    LensShape,
    Magnifier,
    Marker,
    Rect,
    Redaction,
    StepBadge,
)
from core.annotate.primitives import doc_scale, resolve_arrow_side
from core.annotate.svg import build_svg, canvas_size, export_png, render_bytes


def _gradient_png(path: Path, size=(320, 200)) -> Path:
    """Cada pixel distinto: cualquier desplazamiento o fuga se detecta."""
    img = Image.new("RGB", size)
    img.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    img.save(path)
    return path


# --- normalize_crop -------------------------------------------------------

def test_normalize_redondea_a_pixeles_enteros():
    assert normalize_crop(Rect(10.4, 20.6, 100.2, 50.0), (400, 300)) == Rect(10, 21, 101, 50)


def test_normalize_limita_el_recorte_a_la_imagen():
    assert normalize_crop(Rect(-30, -10, 150, 100), (400, 300)) == Rect(0, 0, 120, 90)
    assert normalize_crop(Rect(300, 200, 500, 500), (400, 300)) == Rect(300, 200, 100, 100)


def test_normalize_descarta_lo_muy_pequeno_y_lo_que_cubre_todo():
    assert normalize_crop(None, (400, 300)) is None
    assert normalize_crop(Rect(10, 10, MIN_CROP - 1, 100), (400, 300)) is None
    assert normalize_crop(Rect(10, 10, 100, MIN_CROP - 1), (400, 300)) is None
    assert normalize_crop(Rect(10, 10, MIN_CROP, MIN_CROP), (400, 300)) == Rect(10, 10, MIN_CROP, MIN_CROP)
    assert normalize_crop(Rect(0, 0, 400, 300), (400, 300)) is None
    assert normalize_crop(Rect(-5, -5, 999, 999), (400, 300)) is None  # fuera de la imagen = toda la imagen


def test_asas_del_recorte():
    r = Rect(100, 50, 200, 100)
    assert hit_crop_handle(r, (100, 50), 5) is Handle.NW
    assert hit_crop_handle(r, (300, 100), 5) is Handle.E
    assert hit_crop_handle(r, (200, 100), 5) is None  # el centro no es un asa
    assert resize_crop(r, Handle.E, (400, 100)) == Rect(100, 50, 300, 100)
    # no baja del lado minimo ni se invierte
    assert resize_crop(r, Handle.W, (500, 100)).w == MIN_CROP
    assert full_rect((40, 30)) == Rect(0, 0, 40, 30)


# --- documento ------------------------------------------------------------

def test_view_es_la_imagen_completa_o_el_recorte():
    doc = AnnotationDoc(Path("x.png"), (400, 300))
    assert doc.view == Rect(0, 0, 400, 300)
    doc.crop = Rect(10, 20, 100, 80)
    assert doc.view == Rect(10, 20, 100, 80)


def test_la_escala_automatica_usa_el_ancho_del_recorte():
    doc = AnnotationDoc(Path("x.png"), (3200, 1800))
    assert doc_scale(doc) == 2.0
    doc.crop = Rect(0, 0, 1600, 900)
    assert doc_scale(doc) == 1.0
    doc.style_scale = 3.0   # la manual manda
    assert doc_scale(doc) == 3.0


def test_lado_de_flecha_automatico_mide_el_espacio_dentro_del_recorte():
    m = Marker("m", Rect(500, 100, 100, 50))
    # en la imagen completa el mayor espacio libre esta a la izquierda (500 px)...
    assert resolve_arrow_side(m, (1000, 300), [m], 1.0) is ArrowSide.LEFT
    # ...pero si el recorte empieza en x=450 solo quedan 50 a la izquierda y la flecha va a la derecha
    assert resolve_arrow_side(m, (1000, 300), [m], 1.0, Rect(450, 0, 550, 300)) is ArrowSide.RIGHT


def test_colocacion_automatica_de_la_lupa_respeta_el_recorte():
    src = Rect(300, 200, 80, 60)
    region = Rect(0, 0, 420, 600)   # a la derecha del origen solo quedan 40 px
    c = default_lens_center(src, 2.0, LensShape.ROUNDED, (1000, 600), region=region)
    lens_box = Rect(c[0] - 80, c[1] - 60, 160, 120)   # 80x60 a 2x
    assert lens_box.right <= region.right and lens_box.x >= region.x   # el lente cabe en el recorte
    assert default_lens_center(src, 2.0, LensShape.ROUNDED, (1000, 600))[0] > src.right  # sin recorte, a la derecha


# --- margen y anotaciones fuera -------------------------------------------

def _doc(items, crop=None, size=(800, 500), padding=0):
    return AnnotationDoc(Path("x.png"), size, items, style_scale=1.0, padding=padding, crop=crop)


def test_un_marcador_en_el_borde_del_recorte_pide_margen():
    marcador = Marker("m", Rect(100, 150, 50, 50), ArrowSide.NONE)
    assert required_padding(_doc([marcador])) == 0
    assert required_padding(_doc([marcador], crop=Rect(100, 100, 300, 300))) == 23


def test_lo_que_queda_fuera_del_recorte_no_pide_margen_y_se_avisa():
    fuera = Marker("fuera", Rect(0, 200, 60, 50), ArrowSide.NONE)
    dentro = Marker("dentro", Rect(300, 200, 60, 50), ArrowSide.NONE)
    doc = _doc([fuera, dentro], crop=Rect(150, 100, 400, 300))
    assert required_padding(doc) == 0
    assert items_outside_view(doc) == [fuera]
    assert items_outside_view(_doc([fuera, dentro])) == []   # sin recorte no hay nada fuera


def test_el_pixelado_no_cuenta_como_anotacion_fuera():
    doc = _doc([Redaction("r", Rect(0, 0, 50, 50))], crop=Rect(200, 100, 300, 300))
    assert items_outside_view(doc) == []


# --- sidecar --------------------------------------------------------------

def test_el_recorte_se_guarda_y_se_recupera(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    doc = AnnotationDoc(path, (320, 200), [StepBadge("s", (100, 100), 1)], crop=Rect(40, 30, 200, 120))
    sidecar = save_doc(doc)
    assert load_doc(sidecar).crop == Rect(40, 30, 200, 120)


def test_un_proyecto_viejo_sin_recorte_abre_igual(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    sidecar = save_doc(AnnotationDoc(path, (320, 200), [StepBadge("s", (100, 100), 1)]))
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    del data["crop"]
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    assert load_doc(sidecar).crop is None


@pytest.mark.parametrize("bad", ["x", [1, 2, 3], [0, 0, 10, 10], [None, 0, 100, 100], [True, 0, 100, 100], [0, 0, 5000, 5000]])
def test_un_recorte_invalido_en_el_proyecto_se_ignora(tmp_path, bad):
    path = _gradient_png(tmp_path / "cap.png")
    sidecar = save_doc(AnnotationDoc(path, (320, 200), []))
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["crop"] = bad
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    assert load_doc(sidecar).crop is None


# --- exportar -------------------------------------------------------------

def _full_and_cropped(tmp_path, items, crop, padding=0):
    path = _gradient_png(tmp_path / "cap.png")
    full = AnnotationDoc(path, (320, 200), list(items), style_scale=1.0)
    cropped = AnnotationDoc(path, (320, 200), list(items), style_scale=1.0, padding=padding, crop=crop)
    export_png(full, tmp_path / "full.png")
    export_png(cropped, tmp_path / "crop.png")
    return Image.open(tmp_path / "full.png").convert("RGB"), Image.open(tmp_path / "crop.png").convert("RGB")


def test_el_png_recortado_mide_el_recorte_mas_el_margen(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    doc = AnnotationDoc(path, (320, 200), [], crop=Rect(50, 40, 200, 120), padding=10)
    assert canvas_size(doc) == (220, 140)
    export_png(doc, tmp_path / "out.png")
    assert Image.open(tmp_path / "out.png").size == (220, 140)


def test_el_recorte_exporta_exactamente_esa_region(tmp_path):
    full, cropped = _full_and_cropped(tmp_path, [], Rect(50, 40, 200, 120))
    assert cropped.size == (200, 120)
    assert ImageChops.difference(cropped, full.crop((50, 40, 250, 160))).getbbox() is None


def test_las_anotaciones_quedan_en_su_lugar_tras_recortar(tmp_path):
    items = [
        Marker("m", Rect(100, 80, 80, 50), ArrowSide.NONE),
        StepBadge("s", (200, 120), 1),
    ]
    full, cropped = _full_and_cropped(tmp_path, items, Rect(50, 40, 200, 120))
    assert ImageChops.difference(cropped, full.crop((50, 40, 250, 160))).getbbox() is None
    # y el marcador si esta dibujado (no es un recorte de la imagen limpia)
    clean = Image.open(tmp_path / "cap.png").convert("RGB").crop((50, 40, 250, 160))
    assert ImageChops.difference(cropped, clean).getbbox() is not None


def test_pixelado_y_lupa_leen_el_bitmap_completo(tmp_path):
    items = [
        Redaction("r", Rect(20, 20, 120, 80), 10),   # cruza el borde del recorte
        # el origen de la lupa esta FUERA del recorte; el lente, dentro
        Magnifier("l", Rect(5, 150, 40, 30), (150.0, 100.0), 2.0, LensShape.ROUNDED),
    ]
    full, cropped = _full_and_cropped(tmp_path, items, Rect(50, 40, 200, 120))
    # igual salvo el antialiasing del conector diagonal (unos pocos pixeles, a lo mas 10 niveles)
    diff = ImageChops.difference(cropped, full.crop((50, 40, 250, 160)))
    assert max(max(band) for band in diff.getextrema()) <= 10
    # el lente trae pixeles de fuera del recorte: no es el fondo liso
    assert len(cropped.crop((120, 60, 180, 100)).getcolors(maxcolors=100000)) > 20


def test_el_svg_recortado_no_lleva_los_pixeles_de_fuera(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    doc = AnnotationDoc(path, (320, 200), [], crop=Rect(50, 40, 200, 120))
    svg = build_svg(doc)
    uri = re.search(r'xlink:href="data:image/png;base64,([^"]+)"', svg).group(1)
    embedded = Image.open(io.BytesIO(base64.b64decode(uri)))
    assert embedded.size == (200, 120)   # solo viaja lo recortado
    source = Image.open(path).convert("RGBA").crop((50, 40, 250, 160))
    assert ImageChops.difference(embedded.convert("RGBA"), source).getbbox() is None


def test_sin_recorte_el_svg_no_cambia(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    svg = build_svg(AnnotationDoc(path, (320, 200), []))
    assert '<g transform="translate(0 0)">' in svg and '<image x="0" y="0" width="320" height="200"' in svg


def test_render_bytes_con_recorte(tmp_path):
    path = _gradient_png(tmp_path / "cap.png")
    doc = AnnotationDoc(path, (320, 200), [], crop=Rect(0, 0, 100, 100))
    assert Image.open(io.BytesIO(render_bytes(doc))).size == (100, 100)
