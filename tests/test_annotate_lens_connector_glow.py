import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PIL import Image

from core.annotate import lens, style
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, LensShape, LineStyle, Magnifier, Rect
from core.annotate.palette import Palette
from core.annotate.primitives import PImage, PLine, magnifier_primitives
from core.annotate.svg import export_png

M = Magnifier("l", Rect(100, 100, 80, 60), (400.0, 200.0), 2.0, LensShape.ROUNDED)


def _glow_lines(prims, color=style.GLOW_GOLD):
    return [p for p in prims if isinstance(p, PLine) and p.stroke == color]


# --- dibujo ----------------------------------------------------------------------------

def test_por_defecto_el_conector_no_lleva_resplandor():
    assert _glow_lines(magnifier_primitives(M, 1.0)) == []


def test_con_resplandor_hay_un_halo_de_capas_por_segmento():
    n = len(style.GLOW_RINGS)
    prims = magnifier_primitives(replace(M, connector_glow=True), 1.0)
    glow = _glow_lines(prims)
    assert len(glow) == n * len(lens.connector_segments(M)) == n
    anchos = [p.width for p in glow]
    assert anchos == sorted(anchos, reverse=True)                        # de la mas ancha a la mas angosta
    assert anchos[0] == pytest.approx(2.0 + 2 * style.GLOW_RINGS[-1][0])  # mismo alcance que el resplandor del lente
    opacidades = [p.opacity for p in glow]
    assert opacidades == sorted(opacidades) and all(0 < o < 0.6 for o in opacidades)   # mas tenue hacia afuera
    circular = magnifier_primitives(replace(M, shape=LensShape.CIRCLE, connector_glow=True), 1.0)
    assert len(_glow_lines(circular)) == 2 * n                           # el halo de cada tangente del conector circular


def test_el_resplandor_va_debajo_del_conector_y_de_su_contorno_y_la_imagen_lo_tapa():
    prims = magnifier_primitives(replace(M, connector_glow=True), 1.0)
    glow = _glow_lines(prims)
    ultimo_glow = max(i for i, p in enumerate(prims) if p in glow)
    contorno = next(i for i, p in enumerate(prims) if isinstance(p, PLine) and p.stroke == style.CARD_FILL)
    color = next(i for i, p in enumerate(prims) if isinstance(p, PLine) and p.stroke == style.TAN and p.opacity == 1.0)
    imagen = next(i for i, p in enumerate(prims) if isinstance(p, PImage))
    assert ultimo_glow < contorno < color < imagen


def test_sigue_el_grosor_y_el_estilo_del_conector():
    prims = magnifier_primitives(replace(M, connector_glow=True, connector_width=6.0, connector_style=LineStyle.DOTTED), 2.0)
    glow = _glow_lines(prims)
    assert glow[-1].width == pytest.approx(6.0 * 2 + 2 * style.GLOW_RINGS[0][0] * 2)   # la capa mas angosta: grosor + 2 * primer anillo
    trazo = next(p for p in prims if isinstance(p, PLine) and p.stroke == style.TAN and p.opacity == 1.0)
    assert all((p.dash, p.cap) == (trazo.dash, trazo.cap) for p in glow) and trazo.cap == "round"   # las mismas rayas


def test_el_color_es_el_propio_o_el_de_la_paleta():
    assert _glow_lines(magnifier_primitives(replace(M, connector_glow=True), 1.0, Palette(glow="#112233")), "#112233")
    assert _glow_lines(magnifier_primitives(replace(M, connector_glow=True, glow_color="#AABBCC"), 1.0), "#AABBCC")


def test_sin_conector_no_hay_resplandor_del_conector():
    assert _glow_lines(magnifier_primitives(replace(M, connector=False, connector_glow=True), 1.0)) == []


def test_el_resplandor_del_conector_y_el_del_lente_son_independientes():
    solo_conector = magnifier_primitives(replace(M, connector_glow=True), 1.0)
    dorados = [p for p in solo_conector if getattr(p, "stroke", None) == style.GLOW_GOLD]
    assert len(dorados) == len(style.GLOW_RINGS) and all(isinstance(p, PLine) for p in dorados)   # ni un anillo del lente
    solo_lente = magnifier_primitives(replace(M, glow=True), 1.0)
    assert _glow_lines(solo_lente) == []                                                           # y ninguna franja de conector


def test_los_dos_juntos():
    todo = magnifier_primitives(replace(M, glow=True, connector_glow=True), 1.0)
    assert len([p for p in todo if getattr(p, "stroke", None) == style.GLOW_GOLD]) == 2 * len(style.GLOW_RINGS)


# --- archivo ---------------------------------------------------------------------------------

def test_se_guarda_y_se_recupera_y_una_lupa_vieja_abre_sin_resplandor():
    m = replace(M, connector_glow=True)
    assert item_from_dict(item_to_dict(m)) == m
    data = item_to_dict(M)
    del data["connector_glow"]
    assert item_from_dict(data).connector_glow is False
    for bad in ("si", 1, None, [True]):
        data = item_to_dict(M)
        data["connector_glow"] = bad
        assert item_from_dict(data).connector_glow is False


# --- pixeles: lo que sale en el PNG ----------------------------------------------------------------

def _export(tmp_path, m, name):
    Image.new("RGB", (700, 400), (255, 255, 255)).save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", (700, 400), [m], style_scale=1.0)
    export_png(doc, tmp_path / name)
    return Image.open(tmp_path / name).convert("RGB")


def test_el_conector_resplandece_en_el_png(tmp_path):
    m = replace(M, frame_color="#000000", glow_color="#E8B95C")
    sin = _export(tmp_path, m, "sin.png")
    con = _export(tmp_path, replace(m, connector_glow=True), "con.png")
    (a, b) = lens.connector_segments(m)[0]
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    # un punto a 3 px del eje del conector (perpendicular): dentro de la franja de resplandor, fuera de la linea
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = (dx * dx + dy * dy) ** 0.5
    px, py = round(mx - dy / n * 3), round(my + dx / n * 3)
    assert sin.getpixel((px, py)) == (255, 255, 255)
    r, g, bl = con.getpixel((px, py))
    assert (r, g, bl) != (255, 255, 255) and bl < 235 and r > 200   # un tono calido translucido (el dorado al 30 %)
    # lejos del conector no cambia nada
    assert con.getpixel((650, 380)) == sin.getpixel((650, 380))


# --- interfaz ---------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

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
    t.doc.items.append(replace(M, id="a1"))
    t.controller.select("a1")
    QApplication.processEvents()
    return t


def test_el_panel_activa_el_resplandor_del_conector_y_se_deshace(tab):
    p = tab.panel
    assert p._lens_connector_glow.text() == "Resplandor del conector" and not p._lens_connector_glow.isChecked()
    p._lens_connector_glow.setChecked(True)
    assert tab.controller.selected_item().connector_glow is True
    tab.controller.undo()
    assert tab.controller.selected_item().connector_glow is False and not p._lens_connector_glow.isChecked()


def test_el_color_se_ve_si_alguno_de_los_dos_resplandores_esta_activo(tab):
    p, form = tab.panel, tab.panel._lens_form
    assert not form.isRowVisible(p._lens_glow_color)
    p._lens_connector_glow.setChecked(True)
    assert form.isRowVisible(p._lens_glow_color)          # basta el del conector
    p._lens_glow.setChecked(True)
    p._lens_connector_glow.setChecked(False)
    assert form.isRowVisible(p._lens_glow_color)          # o el del lente
    p._lens_glow.setChecked(False)
    assert not form.isRowVisible(p._lens_glow_color)


def test_sin_conector_se_oculta_su_resplandor(tab):
    p, form = tab.panel, tab.panel._lens_form
    p._lens_connector_glow.setChecked(True)
    p._lens_connector.setChecked(False)
    assert not form.isRowVisible(p._lens_connector_glow) and not form.isRowVisible(p._lens_glow_color)
    p._lens_connector.setChecked(True)
    assert form.isRowVisible(p._lens_connector_glow) and form.isRowVisible(p._lens_glow_color)


def test_cambiar_el_color_del_resplandor_afecta_al_conector(tab, tmp_path):
    p = tab.panel
    p._lens_connector_glow.setChecked(True)
    p._lens_glow_color._on_picked("#00AA00")
    assert tab.controller.selected_item().glow_color == "#00AA00"
    assert _glow_lines(magnifier_primitives(tab.controller.selected_item(), 1.0), "#00AA00")
