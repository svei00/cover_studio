import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest

from core.annotate import style
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, LensShape, LineStyle, Magnifier, Rect
from core.annotate.palette import Palette
from core.annotate.primitives import PCircle, PEllipse, PImage, PLine, PRect, magnifier_primitives
from core.annotate.svg import build_svg

M = Magnifier("l", Rect(100, 100, 80, 60), (400.0, 200.0), 2.0, LensShape.ROUNDED)
GOLD = "#D4C19C"   # el marco por defecto (paleta de marca)


def _split(prims):
    """(origen, conector, marco) = las primitivas de color de cada parte (no los contornos navy)."""
    nuevo = [p for p in prims if getattr(p, "stroke", None) not in (None, style.CARD_FILL, style.GLOW_GOLD)]
    imagen = next(i for i, p in enumerate(prims) if isinstance(p, PImage))
    antes = [p for p in prims[:imagen] if p in nuevo]
    despues = [p for p in prims[imagen + 1:] if p in nuevo]
    origen = [p for p in antes if not isinstance(p, PLine)]
    conector = [p for p in antes if isinstance(p, PLine)]
    return origen, conector, despues


# --- lo de siempre ------------------------------------------------------------------

def test_por_defecto_origen_de_rayas_conector_y_marco_continuos():
    origen, conector, marco = _split(magnifier_primitives(M, 1.0))
    assert origen[0].dash == (6.0, 4.0) and origen[0].width == 2.0 and origen[0].cap == "butt"
    assert conector[0].dash is None and conector[0].width == 2.0
    assert marco[0].dash is None and marco[0].width == 4.0
    assert {p.stroke for p in origen + conector + marco} == {GOLD}


# --- colores independientes ------------------------------------------------------------

def test_cada_parte_tiene_su_color():
    prims = magnifier_primitives(replace(M, frame_color="#111111", source_color="#222222", connector_color="#333333"), 1.0)
    origen, conector, marco = _split(prims)
    assert (origen[0].stroke, conector[0].stroke, marco[0].stroke) == ("#222222", "#333333", "#111111")


def test_origen_y_conector_sin_color_propio_siguen_al_marco():
    origen, conector, marco = _split(magnifier_primitives(replace(M, frame_color="#111111"), 1.0))
    assert {p.stroke for p in origen + conector + marco} == {"#111111"}
    origen, conector, marco = _split(magnifier_primitives(M, 1.0, Palette(lens="#445566")))
    assert {p.stroke for p in origen + conector + marco} == {"#445566"}


def test_cambiar_solo_el_color_del_origen_no_toca_las_otras_partes():
    origen, conector, marco = _split(magnifier_primitives(replace(M, source_color="#222222"), 1.0))
    assert origen[0].stroke == "#222222" and conector[0].stroke == marco[0].stroke == GOLD


# --- grosores independientes ------------------------------------------------------------

def test_grosor_propio_del_origen_y_del_conector_con_su_contorno_navy():
    prims = magnifier_primitives(replace(M, source_width=7.0, connector_width=3.0), 1.0)
    origen, conector, marco = _split(prims)
    assert (origen[0].width, conector[0].width, marco[0].width) == (7.0, 3.0, 4.0)
    navy = [p.width for p in prims if getattr(p, "stroke", None) == style.CARD_FILL]
    assert 9.0 in navy and 5.0 in navy       # ancho + 2 de cada uno
    assert origen[0].dash == (21.0, 14.0)      # las rayas se miden en multiplos del grosor


def test_auto_es_la_mitad_del_marco():
    origen, conector, marco = _split(magnifier_primitives(replace(M, frame_width=10.0), 1.0))
    assert (origen[0].width, conector[0].width, marco[0].width) == (5.0, 5.0, 10.0)
    origen, conector, _ = _split(magnifier_primitives(replace(M, frame_width=10.0, source_width=1.0), 1.0))
    assert (origen[0].width, conector[0].width) == (1.0, 5.0)   # solo el origen es propio


def test_los_grosores_escalan_con_el_trazo():
    origen, conector, marco = _split(magnifier_primitives(replace(M, source_width=7.0), 2.0))
    assert origen[0].width == 14.0 and origen[0].dash == (42.0, 28.0)


# --- estilos de linea ----------------------------------------------------------------------

@pytest.mark.parametrize("estilo,cap", [(LineStyle.DASHED, "butt"), (LineStyle.DOTTED, "round"), (LineStyle.DASH_DOT, "round")])
def test_el_marco_puede_ser_de_rayas_puntos_o_raya_y_punto(estilo, cap):
    _, _, marco = _split(magnifier_primitives(replace(M, frame_style=estilo), 1.0))
    assert marco[0].dash is not None and marco[0].cap == cap


def test_el_origen_continuo_y_el_conector_de_rayas():
    origen, conector, marco = _split(
        magnifier_primitives(replace(M, source_style=LineStyle.SOLID, connector_style=LineStyle.DASHED), 1.0)
    )
    assert origen[0].dash is None and conector[0].dash == (6.0, 4.0) and marco[0].dash is None


@pytest.mark.parametrize("forma,tipo", [(LensShape.CIRCLE, PCircle), (LensShape.ELLIPSE, PEllipse), (LensShape.ROUNDED, PRect)])
def test_los_estilos_aplican_a_cada_forma(forma, tipo):
    m = replace(M, shape=forma, frame_style=LineStyle.DASHED, source_style=LineStyle.DOTTED)
    origen, _, marco = _split(magnifier_primitives(m, 1.0))
    assert isinstance(origen[0], tipo) and origen[0].cap == "round"
    assert isinstance(marco[0], tipo) and marco[0].dash is not None and marco[0].cap == "butt"


def test_el_conector_circular_tiene_dos_tangentes_con_el_mismo_estilo():
    m = replace(M, shape=LensShape.CIRCLE, connector_style=LineStyle.DOTTED, connector_color="#333333")
    _, conector, _ = _split(magnifier_primitives(m, 1.0))
    assert len(conector) == 2 and all(p.stroke == "#333333" and p.cap == "round" for p in conector)


def test_sin_conector_no_hay_lineas():
    _, conector, _ = _split(magnifier_primitives(replace(M, connector=False, connector_color="#333333"), 1.0))
    assert conector == []


def test_el_svg_lleva_las_rayas_de_cada_parte(tmp_path):
    from PIL import Image

    cap = tmp_path / "c.png"
    Image.new("RGB", (600, 400), (255, 255, 255)).save(cap)
    doc = AnnotationDoc(cap, (600, 400), [replace(M, frame_style=LineStyle.DOTTED)], style_scale=1.0)
    svg = build_svg(doc)
    assert 'stroke-linecap="round"' in svg and 'stroke-dasharray="0.040 8.000"' in svg   # el marco de 4 px, a puntos
    assert 'stroke-dasharray="6.000 4.000"' in svg                                       # el origen de siempre


# --- archivo ---------------------------------------------------------------------------------

def test_las_partes_se_guardan_y_se_recuperan():
    m = replace(M, frame_style=LineStyle.DASH_DOT, source_color="#222222", source_width=6.5, source_style=LineStyle.DOTTED,
                connector_color="#333333", connector_width=2.5, connector_style=LineStyle.DASHED)
    assert item_from_dict(item_to_dict(m)) == m
    assert item_from_dict(item_to_dict(M)) == M


def test_una_lupa_vieja_abre_con_el_estilo_de_siempre():
    data = item_to_dict(M)
    for key in ("frame_style", "source_color", "source_width", "source_style", "connector_color", "connector_width", "connector_style"):
        del data[key]
    m = item_from_dict(data)
    assert (m.frame_style, m.source_style, m.connector_style) == (LineStyle.SOLID, LineStyle.DASHED, LineStyle.SOLID)
    assert (m.source_color, m.source_width, m.connector_color, m.connector_width) == (None, None, None, None)


@pytest.mark.parametrize("key,bad,field,expected", [
    ("frame_style", "ondulada", "frame_style", LineStyle.SOLID),
    ("source_style", 5, "source_style", LineStyle.DASHED),
    ("connector_style", None, "connector_style", LineStyle.SOLID),
    ("source_width", 0, "source_width", None), ("source_width", 99, "source_width", None),
    ("connector_width", "x", "connector_width", None), ("connector_width", True, "connector_width", None),
    ("source_color", "rojo", "source_color", None), ("connector_color", 3, "connector_color", None),
])
def test_un_dato_invalido_usa_el_de_fabrica(key, bad, field, expected):
    data = item_to_dict(M)
    data[key] = bad
    assert getattr(item_from_dict(data), field) == expected


# --- interfaz ---------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PIL import Image
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


def _lens(tab):
    return tab.controller.selected_item()


def _reset_btn(control):
    return control.parentWidget().layout().itemAt(1).widget()


def test_el_panel_cambia_los_colores_por_separado(tab):
    p = tab.panel
    p._lens_source_color._on_picked("#222222")
    p._lens_connector_color._on_picked("#333333")
    p._lens_frame._on_picked("#111111")
    m = _lens(tab)
    assert (m.frame_color, m.source_color, m.connector_color) == ("#111111", "#222222", "#333333")
    p._lens_source_color.changed.emit(None)    # volver a seguir al marco
    assert _lens(tab).source_color is None and _lens(tab).connector_color == "#333333"


def test_origen_y_conector_sin_color_propio_muestran_el_del_marco(tab):
    p = tab.panel
    assert p._lens_source_color._picker.hex_color().upper() == GOLD.upper()
    p._lens_frame._on_picked("#111111")
    assert p._lens_source_color._picker.hex_color().lower() == "#111111"
    assert p._lens_connector_color._picker.hex_color().lower() == "#111111"


def test_grosores_y_estilos_desde_el_panel(tab):
    p = tab.panel
    p._lens_source_width.setValue(6.0)
    p._lens_connector_width.setValue(3.0)
    p._lens_frame_style.setCurrentIndex(p._lens_frame_style.findData(LineStyle.DASHED.value))
    p._lens_source_style.setCurrentIndex(p._lens_source_style.findData(LineStyle.SOLID.value))
    p._lens_connector_style.setCurrentIndex(p._lens_connector_style.findData(LineStyle.DOTTED.value))
    m = _lens(tab)
    assert (m.source_width, m.connector_width) == (6.0, 3.0)
    assert (m.frame_style, m.source_style, m.connector_style) == (LineStyle.DASHED, LineStyle.SOLID, LineStyle.DOTTED)
    assert p._lens_source_width.specialValueText() == "Auto"
    p._lens_source_width.setValue(0.0)    # Auto
    assert _lens(tab).source_width is None


def test_restablecer_cada_parte(tab):
    p = tab.panel
    controles = (p._lens_frame_style, p._lens_source_width, p._lens_source_style, p._lens_connector_width, p._lens_connector_style)
    assert not any(_reset_btn(c).isEnabled() for c in controles)
    p._lens_frame_style.setCurrentIndex(p._lens_frame_style.findData(LineStyle.DOTTED.value))
    p._lens_source_width.setValue(5.0)
    p._lens_source_style.setCurrentIndex(p._lens_source_style.findData(LineStyle.SOLID.value))
    p._lens_connector_width.setValue(4.0)
    p._lens_connector_style.setCurrentIndex(p._lens_connector_style.findData(LineStyle.DASHED.value))
    for c in controles:
        assert _reset_btn(c).isEnabled()
        _reset_btn(c).click()
    m = _lens(tab)
    assert (m.frame_style, m.source_width, m.source_style, m.connector_width, m.connector_style) == (
        LineStyle.SOLID, None, LineStyle.DASHED, None, LineStyle.SOLID)


def test_sin_conector_el_panel_oculta_sus_controles(tab):
    p = tab.panel
    form = p._lens_form
    assert form.isRowVisible(p._lens_connector_color) and form.isRowVisible(p._lens_connector_header)
    p._lens_connector.setChecked(False)
    assert not form.isRowVisible(p._lens_connector_color) and not form.isRowVisible(p._lens_connector_header)
    assert not form.isRowVisible(p._lens_connector_width_row) and not form.isRowVisible(p._lens_connector_style_row)
    assert form.isRowVisible(p._lens_source_color)   # el origen sigue siendo editable
    p._lens_connector.setChecked(True)
    assert form.isRowVisible(p._lens_connector_color)


def test_cada_cambio_es_un_paso_de_deshacer_y_los_de_otros_campos_no_se_mezclan(tab):
    p = tab.panel
    pasos = tab.controller.stack.count()
    p._lens_source_style.setCurrentIndex(p._lens_source_style.findData(LineStyle.DOTTED.value))
    p._lens_frame_style.setCurrentIndex(p._lens_frame_style.findData(LineStyle.DASHED.value))
    assert tab.controller.stack.count() == pasos + 2
    tab.controller.undo()
    assert _lens(tab).frame_style is LineStyle.SOLID and _lens(tab).source_style is LineStyle.DOTTED


def test_el_panel_tiene_scroll_y_las_paginas_no_estiran_a_las_demas(tab):
    p = tab.panel
    assert p._scroll.widget().layout().itemAt(0).widget() is p._pages
    altura_lupa = p._pages.sizeHint().height()
    tab.controller.select(None)
    QApplication.processEvents()
    assert p._pages.sizeHint().height() < altura_lupa     # la pagina del documento es mas corta


def test_exportar_con_partes_distintas(tab, tmp_path):
    tab.controller.set_style_scale(1.0)
    p = tab.panel
    p._lens_frame._on_picked("#FF0000")
    p._lens_source_color._on_picked("#00AA00")
    p._lens_connector_color._on_picked("#0000FF")
    p._lens_source_style.setCurrentIndex(p._lens_source_style.findData(LineStyle.SOLID.value))
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    img = Image.open(out).convert("RGB")
    colores = {c for _, c in img.getcolors(maxcolors=100000)}
    assert any(r > 220 and g < 40 and b < 40 for r, g, b in colores)     # el marco rojo
    assert any(g > 140 and r < 40 and b < 40 for r, g, b in colores)     # el origen verde
    assert any(b > 220 and r < 40 and g < 40 for r, g, b in colores)     # el conector azul
