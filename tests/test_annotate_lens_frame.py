import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest

from core.annotate import style
from core.annotate.bounds import required_padding
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, LensShape, Magnifier, Rect
from core.annotate.palette import BRAND_PALETTE, Palette
from core.annotate.primitives import PCircle, PEllipse, PImage, PLine, PRect, magnifier_primitives

SRC = Rect(100, 100, 80, 60)


def _lens(**kw) -> Magnifier:
    return Magnifier("l", SRC, (400.0, 200.0), 2.0, kw.pop("shape", LensShape.ROUNDED), **kw)


def _widths(prims):
    return [p.width for p in prims if isinstance(p, (PCircle, PEllipse, PRect, PLine))]


# --- grosor ---------------------------------------------------------------

def test_el_grosor_por_defecto_no_cambia_el_dibujo_de_siempre():
    # origen punteado (4 y 2) y marco del lente (8 y 4), sin conector
    prims = magnifier_primitives(_lens(shape=LensShape.CIRCLE, connector=False), 1.0)
    assert _widths(prims) == [4, 2, 8, 4]


def test_el_grosor_escala_el_marco_el_origen_y_el_conector():
    prims = magnifier_primitives(_lens(shape=LensShape.CIRCLE, frame_width=10.0, connector=False), 1.0)
    assert _widths(prims) == [7, 5, 14, 10]   # contorno = ancho + 4; origen = mitad


def test_el_grosor_tambien_depende_de_la_escala_de_trazo():
    prims = magnifier_primitives(_lens(frame_width=6.0), 2.0)
    assert max(_widths(prims)) == 20   # (6 + 4) * 2


# --- resplandor -----------------------------------------------------------

def _rings(prims, color=style.GLOW_GOLD):
    return [p for p in prims if getattr(p, "opacity", 1.0) < 0.6 and getattr(p, "stroke", None) == color]


def test_sin_resplandor_no_hay_anillos_y_con_el_hay_nueve():
    assert _rings(magnifier_primitives(_lens(), 1.0)) == []
    assert len(_rings(magnifier_primitives(_lens(glow=True), 1.0))) == len(style.GLOW_RINGS)


@pytest.mark.parametrize("shape,kind", [
    (LensShape.CIRCLE, PCircle), (LensShape.ELLIPSE, PEllipse), (LensShape.ROUNDED, PRect),
])
def test_los_anillos_siguen_la_forma_del_lente(shape, kind):
    rings = _rings(magnifier_primitives(_lens(shape=shape, glow=True), 1.0))
    assert rings and all(isinstance(r, kind) for r in rings)


def test_el_resplandor_va_debajo_de_todo_y_el_lente_lo_tapa():
    prims = magnifier_primitives(_lens(glow=True), 1.0)
    first_image = next(i for i, p in enumerate(prims) if isinstance(p, PImage))
    last_ring = max(i for i, p in enumerate(prims) if p in _rings(prims))
    assert last_ring < first_image
    assert prims.index(_rings(prims)[0]) == 0   # incluso debajo del origen y el conector


def test_el_color_del_resplandor_es_el_propio_o_el_de_la_paleta():
    palette = Palette(glow="#112233")
    anillos = _rings(magnifier_primitives(_lens(glow=True), 1.0, palette), "#112233")
    assert len(anillos) == len(style.GLOW_RINGS)
    propio = magnifier_primitives(_lens(glow=True, glow_color="#AABBCC"), 1.0, palette)
    assert "#AABBCC" in {getattr(p, "stroke", None) for p in propio}


def test_los_anillos_se_alejan_del_marco_y_siguen_su_grosor():
    delgado = _rings(magnifier_primitives(_lens(shape=LensShape.CIRCLE, glow=True, frame_width=2.0), 1.0))
    grueso = _rings(magnifier_primitives(_lens(shape=LensShape.CIRCLE, glow=True, frame_width=12.0), 1.0))
    assert all(g.r > d.r for g, d in zip(grueso, delgado))
    radios = [r.r for r in grueso]
    assert radios == sorted(radios)   # de adentro hacia afuera


def test_el_resplandor_de_la_lupa_pide_margen_en_el_borde():
    lente = Magnifier("l", Rect(300, 200, 80, 60), (60.0, 250.0), 2.0, LensShape.ROUNDED)  # lente pegado a la izquierda
    doc = AnnotationDoc(Path("x.png"), (800, 500), [lente], style_scale=1.0)
    sin = required_padding(doc)
    con = required_padding(replace(doc, items=[replace(lente, glow=True)]))
    assert con > sin


# --- archivo --------------------------------------------------------------

def test_grosor_y_resplandor_se_guardan_y_se_recuperan():
    m = _lens(frame_width=7.5, glow=True, glow_color="#AABBCC")
    assert item_from_dict(item_to_dict(m)) == m


def test_un_proyecto_viejo_de_la_lupa_abre_con_los_valores_de_siempre():
    data = item_to_dict(_lens())
    for key in ("frame_width", "glow", "glow_color"):
        del data[key]
    m = item_from_dict(data)
    assert (m.frame_width, m.glow, m.glow_color) == (style.DEFAULT_LENS_FRAME_WIDTH, False, None)


@pytest.mark.parametrize("bad", ["x", None, True, 0, 99, -3, [4]])
def test_un_grosor_invalido_usa_el_de_siempre(bad):
    data = item_to_dict(_lens())
    data["frame_width"] = bad
    assert item_from_dict(data).frame_width == style.DEFAULT_LENS_FRAME_WIDTH


# --- panel ----------------------------------------------------------------

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication

from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (200, 200, 200)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    t.doc.items.append(Magnifier("a1", Rect(100, 100, 80, 60), (400.0, 200.0), 2.0, LensShape.ROUNDED))
    t.controller.select("a1")
    QApplication.processEvents()
    return t


def test_el_panel_cambia_el_grosor_y_se_deshace(tab):
    tab.panel._lens_frame_width.setValue(9.0)
    assert tab.controller.selected_item().frame_width == 9.0
    tab.controller.undo()
    assert tab.controller.selected_item().frame_width == style.DEFAULT_LENS_FRAME_WIDTH
    assert tab.panel._lens_frame_width.value() == style.DEFAULT_LENS_FRAME_WIDTH


def test_el_panel_activa_el_resplandor_y_muestra_su_color_solo_entonces(tab):
    panel = tab.panel
    assert panel._lens_form.isRowVisible(panel._lens_glow_color) is False
    panel._lens_glow.setChecked(True)
    assert tab.controller.selected_item().glow is True
    assert panel._lens_form.isRowVisible(panel._lens_glow_color) is True
    panel._lens_glow_color._on_picked("#AABBCC")
    assert tab.controller.selected_item().glow_color == "#AABBCC"
    assert BRAND_PALETTE.glow != "#AABBCC"
