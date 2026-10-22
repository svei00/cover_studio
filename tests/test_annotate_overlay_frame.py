"""La sombra y las imagenes pegadas que se salen de la captura se ven en el MARGEN EXTRA (antes se recortaban en el borde)."""

import io
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image

from core.annotate import overlay, raster, style
from core.annotate.bounds import required_padding
from core.annotate.model import AnnotationDoc, ImageOverlay, Marker, Rect
from core.annotate.primitives import doc_scale
from core.annotate.svg import build_svg, render_bytes

CARD = (0x1B, 0x33, 0x50)
RED = (220, 30, 30)
VIEW = Rect(0, 0, 200, 120)


@pytest.fixture
def pic(tmp_path):
    path = tmp_path / "roja.png"
    Image.new("RGBA", (60, 40), RED + (255,)).save(path)
    return path


def _ov(path, rect, **kw):
    return ImageOverlay("p1", str(path), (60, 40), rect, **kw)


def _doc(tmp_path, items, padding=0, crop=None):
    cap = tmp_path / "cap.png"
    Image.new("RGB", (200, 120), (255, 255, 255)).save(cap)
    return AnnotationDoc(image_path=cap, image_size=(200, 120), items=items, padding=padding, crop=crop)


def _png(doc):
    return Image.open(io.BytesIO(render_bytes(doc))).convert("RGB")


# --- geometria de la sombra -------------------------------------------------------------


def test_lo_que_se_ve_de_la_sombra_es_menos_que_su_capa_y_ambos_crecen_con_la_escala():
    for scale in (0.5, 1.0, 2.0):
        assert 0 < overlay.shadow_reach(scale) < overlay.shadow_margin(scale)
    assert overlay.shadow_reach(0.5) < overlay.shadow_reach(1.0) < overlay.shadow_reach(2.0)


def test_la_caja_que_se_ve_incluye_la_sombra_solo_si_esta_activa(pic):
    rect = Rect(50, 40, 60, 40)
    assert overlay.drawn_extent(_ov(pic, rect), 1.0) == rect
    wide = overlay.drawn_extent(_ov(pic, rect, shadow=True), 1.0)
    assert wide == rect.inflate(overlay.shadow_reach(1.0))


def test_la_capa_de_la_sombra_usa_el_mismo_margen_que_se_declara(pic):
    """Una sola fuente de verdad: `raster._shadow_layer` y `overlay.shadow_margin` no pueden divergir."""
    mask = Image.new("L", (60, 40), 255)
    layer, margin = raster._shadow_layer((60, 40), mask, 1.0, 1.0, 1.5)
    assert margin == overlay.shadow_margin(1.5) and layer.size == (60 + 2 * margin, 40 + 2 * margin)


# --- cuando hay marco -------------------------------------------------------------------


def test_sin_margen_o_sin_imagenes_o_sin_nada_fuera_no_hay_marco(pic):
    inside = _ov(pic, Rect(70, 40, 60, 40))
    assert raster.overlay_frame([inside], VIEW, 0, 1.0) is None                       # sin margen
    assert raster.overlay_frame([Marker("m", Rect(1, 1, 5, 5))], VIEW, 40, 1.0) is None   # sin imagenes
    assert raster.overlay_frame([inside], VIEW, 40, 1.0) is None                       # todo cabe
    assert raster.overlay_frame([_ov(pic, Rect(70, 40, 60, 40), shadow=True)], VIEW, 40, 1.0) is None   # con su sombra tambien


def test_una_sombra_que_llega_al_borde_pide_marco(pic):
    flush = _ov(pic, Rect(70, 80, 60, 40), shadow=True)                                # pegada abajo
    assert raster.overlay_frame([flush], VIEW, 40, 1.0) is not None
    assert raster.overlay_frame([_ov(pic, Rect(70, 80, 60, 40))], VIEW, 40, 1.0) is None   # sin sombra no se sale


def test_el_marco_mide_lo_que_el_lienzo_exportado(pic):
    frame = raster.overlay_frame([_ov(pic, Rect(-20, 10, 60, 40))], VIEW, 40, 1.0)
    assert frame.size == (280, 200) and frame.mode == "RGBA"


def test_el_marco_es_el_relleno_de_la_tarjeta_donde_no_hay_nada(pic):
    frame = raster.overlay_frame([_ov(pic, Rect(-20, 10, 60, 40))], VIEW, 40, 1.0)
    assert frame.getpixel((270, 190)) == CARD + (255,) and frame.getpixel((140, 10)) == CARD + (255,)


def test_una_imagen_que_se_sale_se_ve_en_el_margen(pic):
    frame = raster.overlay_frame([_ov(pic, Rect(-20, 10, 60, 40))], VIEW, 40, 1.0)
    assert frame.getpixel((40 - 10, 40 + 30)) == RED + (255,)                          # la parte que cuelga a la izquierda


def test_la_sombra_cae_en_el_margen_de_abajo_y_se_desvanece(pic):
    frame = raster.overlay_frame([_ov(pic, Rect(70, 80, 60, 40), shadow=True)], VIEW, 60, 1.0)
    just_below = frame.getpixel((60 + 100, 60 + 120 + 4))
    far = frame.getpixel((60 + 100, 60 + 120 + 50))
    assert sum(just_below[:3]) < sum(CARD)                                             # oscurece el relleno
    assert far == CARD + (255,)                                                        # y a la distancia se desvanece del todo


def test_con_recorte_el_marco_rodea_la_zona_exportada(pic):
    crop = Rect(50, 30, 100, 60)
    frame = raster.overlay_frame([_ov(pic, Rect(20, 30, 40, 40))], crop, 20, 1.0)
    assert frame.size == (140, 100)
    assert frame.getpixel((5, 20)) == RED + (255,)                                      # fuente x=35: fuera del recorte, dentro del margen


# --- exportacion ------------------------------------------------------------------------


def test_exportar_muestra_la_sombra_en_el_margen_en_vez_de_cortarla(tmp_path, pic):
    flush = _ov(pic, Rect(70, 80, 60, 40), shadow=True)
    out = _png(_doc(tmp_path, [flush], padding=60))
    assert out.size == (320, 240)
    below = out.getpixel((60 + 100, 60 + 120 + 4))
    assert sum(below) < sum(CARD)                                                      # antes: relleno liso, sin sombra
    assert out.getpixel((10, 10)) == CARD


def test_sin_margen_la_exportacion_no_cambia(tmp_path, pic):
    flush = _ov(pic, Rect(70, 80, 60, 40), shadow=True)
    assert _png(_doc(tmp_path, [flush], padding=0)).size == (200, 120)


def test_el_svg_solo_lleva_el_marco_cuando_hace_falta(tmp_path, pic):
    inside = _doc(tmp_path, [_ov(pic, Rect(70, 40, 60, 40), shadow=True)], padding=40)
    assert build_svg(inside).count("<image") == 1 and "<rect" in build_svg(inside)       # como siempre
    out = _doc(tmp_path, [_ov(pic, Rect(70, 80, 60, 40), shadow=True)], padding=60)
    svg = build_svg(out)
    assert svg.count("<image") == 2 and f'fill="{style.CARD_FILL}"' not in svg           # el marco reemplaza al relleno liso


def test_el_marco_no_tapa_a_las_anotaciones(tmp_path, pic):
    items = [_ov(pic, Rect(70, 80, 60, 40), shadow=True), Marker("m", Rect(10, 10, 60, 40))]
    out = _png(_doc(tmp_path, items, padding=60))
    plain = _png(_doc(tmp_path, [Marker("m", Rect(10, 10, 60, 40))], padding=60))
    assert out.getpixel((60 + 10, 60 + 30)) == plain.getpixel((60 + 10, 60 + 30))        # el borde del marcador, igual


# --- cuanto margen hace falta -------------------------------------------------------------


def test_una_imagen_dentro_no_pide_margen(tmp_path, pic):
    assert required_padding(_doc(tmp_path, [_ov(pic, Rect(70, 40, 60, 40))])) == 0
    assert required_padding(_doc(tmp_path, [_ov(pic, Rect(70, 40, 60, 40), shadow=True)])) == 0


def test_una_imagen_que_cuelga_pide_justo_lo_que_cuelga(tmp_path, pic):
    assert required_padding(_doc(tmp_path, [_ov(pic, Rect(-30, 10, 60, 40))])) == 30
    assert required_padding(_doc(tmp_path, [_ov(pic, Rect(170, 10, 60, 40))])) == 30      # sale 30 por la derecha


def test_la_sombra_pegada_al_borde_pide_lo_que_se_ve_de_ella(tmp_path, pic):
    doc = _doc(tmp_path, [_ov(pic, Rect(70, 80, 60, 40), shadow=True)])
    assert required_padding(doc) == math.ceil(overlay.shadow_reach(doc_scale(doc)))
    assert required_padding(_doc(tmp_path, [_ov(pic, Rect(70, 80, 60, 40))])) == 0        # sin sombra no se sale


def test_con_ese_margen_la_sombra_cabe_entera(tmp_path, pic):
    items = [_ov(pic, Rect(70, 80, 60, 40), shadow=True)]
    need = required_padding(_doc(tmp_path, items))
    doc = _doc(tmp_path, items, padding=need)
    assert required_padding(doc) == need                                               # es independiente del margen que ya tenga
    out = _png(doc)
    assert out.size == (200 + 2 * need, 120 + 2 * need)
    last = out.getpixel((need + 100, need + 120 + need - 1))
    assert all(abs(a - b) <= 2 for a, b in zip(last, CARD))                            # la ultima fila del margen ya casi no tiene sombra
    assert sum(out.getpixel((need + 100, need + 120 + 4))) < sum(last)                  # y mas cerca de la imagen si se nota


def test_una_imagen_fuera_del_recorte_no_pide_margen_pero_se_avisa_como_fuera(tmp_path, pic):
    from core.annotate.bounds import items_outside_view
    crop = Rect(100, 0, 100, 120)
    doc = _doc(tmp_path, [_ov(pic, Rect(0, 10, 60, 40))], crop=crop)
    assert required_padding(doc) == 0
    assert [i.id for i in items_outside_view(doc)] == ["p1"]


# --- vista previa (Qt) ----------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.annotate import tab as tab_module
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(tab_module, "captures_dir", lambda: tmp_path / "capturas")
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "cap.png")
    Image.new("RGB", (120, 80), RED).save(tmp_path / "roja.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _add(tab, tmp_path, rect, **edits):
    tab.controller.add_overlay(tmp_path / "roja.png", (120, 80))
    tab.controller.edit_selected(_merge=False, rect=rect, **edits)
    QApplication.processEvents()


def test_sin_margen_no_hay_marco_en_pantalla(tab, tmp_path):
    _add(tab, tmp_path, Rect(100, 220, 120, 80), shadow=True)
    assert tab._frame_qimage is None and tab.canvas._frame_image is None


def test_con_margen_y_sombra_en_el_borde_la_pantalla_recibe_el_marco(tab, tmp_path):
    tab.controller.set_padding(80)
    _add(tab, tmp_path, Rect(100, 220, 120, 80), shadow=True)
    frame = tab._frame_qimage
    assert frame is not None and (frame.width(), frame.height()) == (400 + 160, 300 + 160)
    assert tab.canvas._frame_image is frame


def test_la_pantalla_pinta_la_sombra_en_el_margen_igual_que_la_exportacion(tab, tmp_path):
    tab.controller.set_padding(80)
    _add(tab, tmp_path, Rect(100, 220, 120, 80))                                       # sin sombra
    tab.controller.select(None)
    QApplication.processEvents()
    pt = tab.canvas.image_to_view((160, 306)).toPoint()                                 # justo debajo de la imagen, en el margen
    plain = tab.canvas.grab().toImage().pixelColor(pt)
    tab.controller.select(tab.doc.items[0].id)
    tab.controller.edit_selected(_merge=False, shadow=True)
    tab.controller.select(None)
    QApplication.processEvents()
    shadowed = tab.canvas.grab().toImage().pixelColor(pt)
    assert plain.red() + plain.green() + plain.blue() > shadowed.red() + shadowed.green() + shadowed.blue()
    out = Image.open(io.BytesIO(render_bytes(tab.doc))).convert("RGB")
    assert sum(out.getpixel((80 + 160, 80 + 306))) < sum(CARD)                          # y la exportacion tambien


def test_al_meter_la_imagen_otra_vez_el_marco_desaparece(tab, tmp_path):
    tab.controller.set_padding(80)
    _add(tab, tmp_path, Rect(100, 220, 120, 80), shadow=True)
    assert tab._frame_qimage is not None
    tab.controller.edit_selected(_merge=False, rect=Rect(100, 100, 120, 80))
    QApplication.processEvents()
    assert tab._frame_qimage is None and tab.canvas._frame_image is None


def test_cambiar_el_margen_rehace_el_marco(tab, tmp_path):
    tab.controller.set_padding(60)
    _add(tab, tmp_path, Rect(100, 220, 120, 80), shadow=True)
    assert (tab._frame_qimage.width(), tab._frame_qimage.height()) == (520, 420)
    tab.controller.set_padding(100)
    QApplication.processEvents()
    assert (tab._frame_qimage.width(), tab._frame_qimage.height()) == (600, 500)


def test_abrir_otra_captura_no_arrastra_el_marco(tab, tmp_path):
    tab.controller.set_padding(80)
    _add(tab, tmp_path, Rect(100, 220, 120, 80), shadow=True)
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "otra.png")
    tab.load_capture(tmp_path / "otra.png")
    QApplication.processEvents()
    assert tab._frame_qimage is None
