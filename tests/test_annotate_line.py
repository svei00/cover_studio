import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Arrow, HeadStyle, LineStyle
from core.annotate.primitives import PCircle, PLine, PPolygon, arrow_primitives, dash_pattern
from core.annotate.svg import export_png, primitive_to_svg

A = Arrow("a", (100.0, 100.0), (300.0, 100.0))
LINE = replace(A, head_end=HeadStyle.NONE, glow=False)


def _kinds(prims):
    return [type(p).__name__ for p in prims]


# --- lo de siempre ----------------------------------------------------------------

def test_la_flecha_por_defecto_es_la_de_siempre():
    prims = arrow_primitives(A, 1.0)
    assert _kinds(prims) == ["PLine", "PLine", "PPolygon", "PPolygon"]   # resplandor, linea, resplandor y punta
    linea = prims[1]
    assert (linea.a, linea.b, linea.width, linea.dash, linea.cap) == ((100.0, 100.0), (300.0, 100.0), 5.0, None, "butt")
    assert prims[3].points[0] == (300.0, 100.0) and prims[3].fill == style.RED


# --- puntas -----------------------------------------------------------------------

def test_sin_puntas_es_una_linea():
    assert _kinds(arrow_primitives(LINE, 1.0)) == ["PLine"]
    assert _kinds(arrow_primitives(replace(LINE, glow=True), 1.0)) == ["PLine", "PLine"]


def test_punta_inicial_y_final():
    solo_inicio = arrow_primitives(replace(LINE, head_start=HeadStyle.ARROW), 1.0)
    assert _kinds(solo_inicio) == ["PLine", "PPolygon"] and solo_inicio[1].points[0] == (100.0, 100.0)
    # la punta del inicio mira hacia AFUERA: su base queda hacia el interior de la linea (x mayor)
    assert solo_inicio[1].points[1][0] > 100.0
    ambas = arrow_primitives(replace(LINE, head_start=HeadStyle.ARROW, head_end=HeadStyle.ARROW), 1.0)
    assert _kinds(ambas) == ["PLine", "PPolygon", "PPolygon"]
    tips = sorted(p.points[0] for p in ambas if isinstance(p, PPolygon))
    assert tips == [(100.0, 100.0), (300.0, 100.0)]
    assert [p.points[1][0] for p in ambas if isinstance(p, PPolygon)][0] < 300.0   # la del final: base hacia dentro


def test_punta_de_punto():
    prims = arrow_primitives(replace(LINE, head_end=HeadStyle.DOT), 1.0)
    assert _kinds(prims) == ["PLine", "PCircle"]
    punto = prims[1]
    assert punto.center == (300.0, 100.0) and punto.fill == style.RED and punto.r >= 5.0 * 1.2
    con_resplandor = arrow_primitives(replace(LINE, head_end=HeadStyle.DOT, glow=True), 1.0)
    assert _kinds(con_resplandor) == ["PLine", "PLine", "PCircle", "PCircle"]


def test_la_punta_sigue_al_grosor_con_limites():
    def alto(width):
        puntas = [p for p in arrow_primitives(replace(A, width=width, glow=False), 1.0) if isinstance(p, PPolygon)]
        return abs(puntas[0].points[1][1] - puntas[0].points[2][1])

    assert alto(1.0) < alto(5.0) < alto(10.0)
    assert alto(5.0) == pytest.approx(2 * 13 * 0.8)        # la de siempre: 13 px de punta
    assert alto(24.0) == pytest.approx(alto(15.0))         # tope: 3x
    assert alto(1.0) == pytest.approx(alto(2.5))           # piso: 0.5x


def test_longitud_cero_no_dibuja_nada():
    assert arrow_primitives(replace(A, end=A.start), 1.0) == []


# --- grosor y estilos --------------------------------------------------------------

def test_grosor_y_escala():
    assert arrow_primitives(replace(LINE, width=8.0), 2.0)[0].width == 16.0


@pytest.mark.parametrize("estilo,patron,remate", [
    (LineStyle.SOLID, None, "butt"),
    (LineStyle.DASHED, (15.0, 10.0), "butt"),
    (LineStyle.DOTTED, (0.05, 10.0), "round"),
    (LineStyle.DASH_DOT, (10.0, 12.5, 0.05, 12.5), "round"),
])
def test_patrones_de_rayas_para_un_trazo_de_5(estilo, patron, remate):
    dash, cap = dash_pattern(estilo, 5.0)
    assert cap == remate
    assert dash == pytest.approx(patron) if patron else dash is None


def test_las_rayas_se_miden_en_multiplos_del_grosor():
    d5, _ = dash_pattern(LineStyle.DASHED, 5.0)
    d10, _ = dash_pattern(LineStyle.DASHED, 10.0)
    assert d10 == pytest.approx(tuple(2 * v for v in d5))


def test_la_linea_y_su_resplandor_llevan_las_rayas():
    prims = arrow_primitives(replace(LINE, line_style=LineStyle.DOTTED, glow=True), 1.0)
    assert prims[0].dash == prims[1].dash and prims[0].cap == prims[1].cap == "round"
    assert prims[0].width > prims[1].width   # el resplandor es mas ancho


def test_svg_de_los_estilos():
    solida = primitive_to_svg(arrow_primitives(LINE, 1.0)[0])
    assert "dasharray" not in solida and "linecap" not in solida
    rayas = primitive_to_svg(arrow_primitives(replace(LINE, line_style=LineStyle.DASHED), 1.0)[0])
    assert 'stroke-dasharray="15.000 10.000"' in rayas and "linecap" not in rayas
    puntos = primitive_to_svg(arrow_primitives(replace(LINE, line_style=LineStyle.DOTTED), 1.0)[0])
    assert 'stroke-dasharray="0.050 10.000"' in puntos and 'stroke-linecap="round"' in puntos


def test_los_estilos_de_linea_en_otras_primitivas_tambien_se_escriben():
    circulo = PCircle((50.0, 50.0), 20.0, None, "#fff", 2.0, dash=(0.02, 4.0), cap="round")
    assert 'stroke-linecap="round"' in primitive_to_svg(circulo)


# --- archivo ---------------------------------------------------------------------------

def test_la_linea_se_guarda_y_se_recupera():
    a = Arrow("a", (1.0, 2.0), (30.0, 40.0), False, "#111111", "#222222",
              HeadStyle.DOT, HeadStyle.ARROW, LineStyle.DASH_DOT, 9.5)
    assert item_from_dict(item_to_dict(a)) == a
    assert item_from_dict(item_to_dict(A)) == A


def test_una_flecha_vieja_abre_igual():
    data = {"type": "arrow", "id": "a", "start": [1, 2], "end": [3, 4], "glow": True, "color": None, "glow_color": None}
    a = item_from_dict(data)
    assert (a.head_start, a.head_end, a.line_style, a.width) == (HeadStyle.NONE, HeadStyle.ARROW, LineStyle.SOLID, 5.0)


@pytest.mark.parametrize("key,bad,field,expected", [
    ("head_start", "estrella", "head_start", HeadStyle.NONE),
    ("head_end", 7, "head_end", HeadStyle.ARROW),
    ("line_style", "ondulada", "line_style", LineStyle.SOLID),
    ("width", 0, "width", 5.0), ("width", 99, "width", 5.0), ("width", "x", "width", 5.0), ("width", True, "width", 5.0),
])
def test_un_dato_invalido_de_la_linea_usa_el_de_fabrica(key, bad, field, expected):
    data = item_to_dict(A)
    data[key] = bad
    assert getattr(item_from_dict(data), field) == expected


# --- medido: resvg y Qt dibujan las rayas igual -----------------------------------------------

def _tinta(valores):
    return sum(1 for v in valores if v < 128) / len(valores)


@pytest.mark.parametrize("estilo", [LineStyle.DASHED, LineStyle.DOTTED, LineStyle.DASH_DOT])
def test_las_rayas_son_las_mismas_en_resvg_y_en_el_pintor_de_qt(tmp_path, estilo):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    linea = Arrow("a", (20.0, 50.0), (380.0, 50.0), False, "#000000", None, HeadStyle.NONE, HeadStyle.NONE, estilo, 6.0)
    doc = AnnotationDoc(Path(tmp_path / "c.png"), (400, 100), [linea], style_scale=1.0)
    Image.new("RGB", (400, 100), (255, 255, 255)).save(doc.image_path)
    export_png(doc, tmp_path / "out.png")
    resvg = Image.open(tmp_path / "out.png").convert("L")
    fila_resvg = [resvg.getpixel((x, 50)) for x in range(25, 375)]

    img = QImage(400, 100, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    paint_primitives(painter, arrow_primitives(linea, 1.0))
    painter.end()
    fila_qt = [QColor(img.pixel(x, 50)).red() for x in range(25, 375)]

    # tienen huecos de verdad (no es una linea continua) y casi la misma proporcion de tinta
    assert 0.2 < _tinta(fila_resvg) < 0.85
    assert abs(_tinta(fila_resvg) - _tinta(fila_qt)) < 0.08


# --- interfaz ---------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.annotate.controller import STICKY_TOOLS, Tool
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
    t.controller.set_style_scale(1.0)
    QApplication.processEvents()
    return t


def _drag(canvas, a, b):
    for kind, pt, buttons, button in (
        (QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton),
        (QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton),
        (QEvent.MouseButtonRelease, b, Qt.NoButton, Qt.LeftButton),
    ):
        pos = canvas.image_to_view(pt)
        QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def _reset_btn(control):
    return control.parentWidget().layout().itemAt(1).widget()


def test_la_herramienta_linea_crea_una_flecha_sin_puntas_y_se_repite(tab):
    assert Tool.LINE in tab.tool_buttons and Tool.LINE in STICKY_TOOLS
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100, 100), (300, 160))
    _drag(tab.canvas, (100, 300), (300, 360))
    assert len(tab.doc.items) == 2 and tab.controller.tool is Tool.LINE
    linea = tab.doc.items[0]
    assert isinstance(linea, Arrow) and linea.head_start is HeadStyle.NONE and linea.head_end is HeadStyle.NONE
    assert tab.panel._title.text() == "Linea"


def test_la_herramienta_flecha_sigue_creando_flechas(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100, 100), (300, 160))
    assert tab.doc.items[0].head_end is HeadStyle.ARROW and tab.panel._title.text() == "Flecha"


def test_el_panel_cambia_puntas_estilo_y_grosor_y_el_titulo(tab):
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100, 100), (300, 160))
    p = tab.panel
    p._arrow_head_end.setCurrentIndex(p._arrow_head_end.findData(HeadStyle.ARROW.value))
    p._arrow_head_start.setCurrentIndex(p._arrow_head_start.findData(HeadStyle.DOT.value))
    p._arrow_style.setCurrentIndex(p._arrow_style.findData(LineStyle.DASHED.value))
    p._arrow_width.setValue(9.0)
    a = tab.controller.selected_item()
    assert (a.head_start, a.head_end, a.line_style, a.width) == (HeadStyle.DOT, HeadStyle.ARROW, LineStyle.DASHED, 9.0)
    assert p._title.text() == "Flecha"
    p._arrow_head_end.setCurrentIndex(p._arrow_head_end.findData(HeadStyle.NONE.value))
    p._arrow_head_start.setCurrentIndex(p._arrow_head_start.findData(HeadStyle.NONE.value))
    assert p._title.text() == "Linea"
    assert [p._arrow_style.itemData(i) for i in range(p._arrow_style.count())] == ["solid", "dashed", "dotted", "dash-dot"]


def test_restablecer_estilo_grosor_y_puntas(tab):
    tab.tool_buttons[Tool.ARROW].click()
    _drag(tab.canvas, (100, 100), (300, 160))
    p = tab.panel
    assert not any(_reset_btn(c).isEnabled() for c in (p._arrow_style, p._arrow_width, p._arrow_head_end))
    p._arrow_style.setCurrentIndex(p._arrow_style.findData(LineStyle.DOTTED.value))
    p._arrow_width.setValue(12.0)
    p._arrow_head_end.setCurrentIndex(p._arrow_head_end.findData(HeadStyle.DOT.value))
    for control in (p._arrow_style, p._arrow_width, p._arrow_head_end):
        assert _reset_btn(control).isEnabled()
        _reset_btn(control).click()
    a = tab.controller.selected_item()
    assert (a.line_style, a.width, a.head_end) == (LineStyle.SOLID, 5.0, HeadStyle.ARROW)


def test_la_linea_se_selecciona_se_mueve_y_se_exporta_con_su_estilo(tab, tmp_path):
    tab.tool_buttons[Tool.LINE].click()
    _drag(tab.canvas, (100, 250), (500, 250))
    p = tab.panel
    p._arrow_style.setCurrentIndex(p._arrow_style.findData(LineStyle.DASHED.value))
    p._arrow_width.setValue(6.0)
    p._arrow_glow.setChecked(False)
    p._arrow_color._on_picked("#000000")
    tab.tool_buttons[Tool.SELECT].click()
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    fila = [Image.open(out).convert("L").getpixel((x, 250)) for x in range(110, 490)]
    assert any(v < 60 for v in fila) and any(v > 230 for v in fila)   # hay tinta y hay huecos: va a rayas
