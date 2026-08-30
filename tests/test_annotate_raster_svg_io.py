import base64
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.errors import AnnotateError
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc, sidecar_path
from core.annotate.model import (
    AnnotationDoc,
    Arrow,
    ArrowSide,
    Marker,
    Rect,
    Redaction,
    StepBadge,
    TextAlign,
    TextLabel,
)
from core.annotate.raster import apply_redactions, load_image
from core.annotate.svg import build_svg, default_output_path, export_png, export_svg


def _gradient_png(path: Path, size=(320, 200)) -> Path:
    """Cada pixel distinto: cualquier fuga de la zona original se detecta."""
    img = Image.new("RGB", size)
    img.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    img.save(path)
    return path


# --- raster ---------------------------------------------------------------

def test_load_image_errores_claros(tmp_path):
    with pytest.raises(AnnotateError):
        load_image(tmp_path / "no_existe.png")
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"x")
    with pytest.raises(AnnotateError):
        load_image(gif)
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"no soy una imagen")
    with pytest.raises(AnnotateError):
        load_image(roto)


def test_load_image_devuelve_rgba(tmp_path):
    img = load_image(_gradient_png(tmp_path / "a.png"))
    assert img.mode == "RGBA" and img.size == (320, 200)


def test_apply_redactions_vuelve_uniformes_los_bloques(tmp_path):
    img = load_image(_gradient_png(tmp_path / "a.png"))
    out = apply_redactions(img, [Redaction("r", Rect(0, 0, 60, 60), block=20)])
    for bx in range(3):
        for by in range(3):
            colors = {out.getpixel((bx * 20 + dx, by * 20 + dy)) for dx in range(20) for dy in range(20)}
            assert len(colors) == 1


def test_apply_redactions_no_toca_fuera_de_la_zona_ni_muta_el_original(tmp_path):
    img = load_image(_gradient_png(tmp_path / "a.png"))
    before = img.copy()
    out = apply_redactions(img, [Redaction("r", Rect(0, 0, 60, 60), block=20)])
    assert img.tobytes() == before.tobytes()
    assert out.getpixel((200, 150)) == img.getpixel((200, 150))
    assert out.getpixel((10, 10)) != img.getpixel((10, 10))


def test_apply_redactions_recorta_zonas_fuera_de_la_imagen(tmp_path):
    img = load_image(_gradient_png(tmp_path / "a.png"))
    fuera = apply_redactions(img, [Redaction("r", Rect(1000, 1000, 50, 50))])
    assert fuera.tobytes() == img.tobytes()
    parcial = apply_redactions(img, [Redaction("r", Rect(300, 180, 100, 100), block=10)])
    assert parcial.size == img.size


def test_apply_redactions_rect_menor_que_el_bloque_igual_pixela(tmp_path):
    img = load_image(_gradient_png(tmp_path / "a.png"))
    out = apply_redactions(img, [Redaction("r", Rect(10, 10, 6, 6), block=20)])
    colors = {out.getpixel((10 + dx, 10 + dy)) for dx in range(6) for dy in range(6)}
    assert len(colors) == 1


# --- svg / exportar -------------------------------------------------------

def _doc(tmp_path, items, padding=0, size=(320, 200)):
    return AnnotationDoc(_gradient_png(tmp_path / "cap.png", size), size, items, padding=padding)


def _embedded_png(svg: str) -> Image.Image:
    match = re.search(r'xlink:href="data:image/png;base64,([^"]+)"', svg)
    assert match
    return Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert("RGBA")


def test_svg_incrusta_el_bitmap_pixelado_y_no_el_original(tmp_path):
    doc = _doc(tmp_path, [Redaction("r", Rect(0, 0, 60, 60), block=20)])
    original = load_image(doc.image_path)
    embedded = _embedded_png(build_svg(doc))
    assert embedded.getpixel((10, 10)) != original.getpixel((10, 10))
    assert len({embedded.getpixel((x, y)) for x in range(20) for y in range(20)}) == 1
    # el archivo original en base64 tampoco aparece
    assert base64.b64encode(doc.image_path.read_bytes()).decode()[:200] not in build_svg(doc)


def test_svg_escapa_el_texto_de_las_etiquetas(tmp_path):
    doc = _doc(tmp_path, [TextLabel("t", (10.0, 10.0), "Tips & <Trucos>")])
    svg = build_svg(doc)
    assert "Tips &amp; &lt;Trucos&gt;" in svg
    assert "<Trucos>" not in svg


def test_svg_texto_suelto_lleva_contorno(tmp_path):
    doc = _doc(tmp_path, [TextLabel("t", (10.0, 10.0), "x", bg=None, border=None, outline=style.PAGE_BG)])
    assert 'paint-order="stroke fill"' in build_svg(doc)


def test_svg_con_padding_agranda_el_lienzo_y_rellena(tmp_path):
    doc = _doc(tmp_path, [], padding=30)
    svg = build_svg(doc)
    assert 'viewBox="0 0 380 260"' in svg
    assert f'fill="{style.CARD_FILL}"' in svg and "translate(30 30)" in svg


def test_build_svg_rechaza_captura_con_otro_tamano(tmp_path):
    doc = _doc(tmp_path, [])
    doc.image_size = (999, 999)
    with pytest.raises(AnnotateError):
        build_svg(doc)


def test_export_png_tamano_y_pixel_del_marcador(tmp_path):
    doc = _doc(tmp_path, [Marker("m", Rect(100, 60, 80, 40), arrow=ArrowSide.NONE)])
    out = tmp_path / "salida.png"
    export_png(doc, out)
    img = Image.open(out).convert("RGB")
    assert img.size == (320, 200)
    r, g, b = img.getpixel((100, 80))
    assert abs(r - 0x62) < 12 and abs(g - 0x11) < 12 and abs(b - 0x32) < 12


def test_export_png_con_padding_suma_el_margen(tmp_path):
    doc = _doc(tmp_path, [], padding=20)
    out = tmp_path / "salida.png"
    export_png(doc, out)
    assert Image.open(out).size == (360, 240)


def test_export_png_no_sobrescribe_el_original_por_defecto(tmp_path):
    doc = _doc(tmp_path, [])
    antes = doc.image_path.read_bytes()
    with pytest.raises(AnnotateError):
        export_png(doc, doc.image_path)
    assert doc.image_path.read_bytes() == antes
    export_png(doc, doc.image_path, allow_overwrite=True)
    assert doc.image_path.read_bytes() != antes


def test_export_svg_escribe_archivo(tmp_path):
    doc = _doc(tmp_path, [Arrow("a", (10.0, 10.0), (100.0, 10.0))])
    out = tmp_path / "salida.svg"
    export_svg(doc, out)
    assert out.read_text(encoding="utf-8").startswith("<svg")


def test_default_output_path():
    assert default_output_path(Path("C:/x/captura.png")) == Path("C:/x/captura-anotada.png")


# --- io -------------------------------------------------------------------

ALL_ITEMS = [
    Marker("m", Rect(1, 2, 3, 4), ArrowSide.TOP, glow=False),
    Arrow("a", (1.0, 2.0), (3.0, 4.0)),
    StepBadge("s", (5.0, 6.0), 7),
    TextLabel("t", (8.0, 9.0), "hola\nmundo", size=30.0, bg=None, border=None, outline="#000000",
              align=TextAlign.CENTER, bold=False),
    Redaction("r", Rect(10, 11, 12, 13), 8),
]


@pytest.mark.parametrize("item", ALL_ITEMS, ids=lambda i: type(i).__name__)
def test_item_ida_y_vuelta(item):
    assert item_from_dict(item_to_dict(item)) == item


def test_sidecar_path():
    assert sidecar_path(Path("C:/x/captura.png")) == Path("C:/x/captura.anotar.json")


def test_save_y_load_doc_ida_y_vuelta(tmp_path):
    doc = AnnotationDoc(tmp_path / "cap.png", (320, 200), list(ALL_ITEMS), style_scale=1.5, padding=12)
    saved = save_doc(doc)
    assert saved == tmp_path / "cap.anotar.json"
    loaded = load_doc(saved)
    assert loaded.items == doc.items and loaded.style_scale == 1.5 and loaded.padding == 12
    assert loaded.image_path == tmp_path / "cap.png" and loaded.image_size == (320, 200)


def test_load_doc_resuelve_la_captura_relativa_al_json(tmp_path):
    doc = AnnotationDoc(tmp_path / "cap.png", (10, 10), [])
    saved = save_doc(doc)
    movida = tmp_path / "otra"
    movida.mkdir()
    nuevo = movida / saved.name
    nuevo.write_text(saved.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_doc(nuevo).image_path == movida / "cap.png"


def test_load_doc_errores_claros(tmp_path):
    with pytest.raises(AnnotateError):
        load_doc(tmp_path / "no_existe.json")
    malo = tmp_path / "malo.json"
    malo.write_text("{ no es json", encoding="utf-8")
    with pytest.raises(AnnotateError):
        load_doc(malo)
    incompleto = tmp_path / "inc.json"
    incompleto.write_text('{"version": 1}', encoding="utf-8")
    with pytest.raises(AnnotateError):
        load_doc(incompleto)


def test_item_from_dict_tipo_desconocido():
    with pytest.raises(AnnotateError):
        item_from_dict({"type": "dragon", "id": "x"})
    with pytest.raises(AnnotateError):
        item_from_dict({"type": "marker", "id": "x"})
