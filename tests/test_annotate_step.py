import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest

from core.annotate import edit, style
from core.annotate.bounds import required_padding
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Rect, StepBadge, StepShape
from core.annotate.palette import Palette
from core.annotate.primitives import PCircle, PPolygon, PRect, PText, item_bounds, step_extent, step_primitives

S = StepBadge("s", (100.0, 100.0), 3)


def _kinds(prims):
    return [type(p).__name__ for p in prims]


# --- el dibujo de siempre no cambia -------------------------------------------

def test_el_paso_por_defecto_es_exactamente_el_de_siempre():
    assert step_primitives(S, 1.0) == [
        PCircle((100.0, 100.0), 20.0, style.CARD_FILL, style.GOLD, 2.5),
        PText((100.0, 100.0), "3", 17.0, style.GOLD, True, "middle"),
    ]
    assert step_primitives(S, 2.0)[0] == PCircle((100.0, 100.0), 40.0, style.CARD_FILL, style.GOLD, 5.0)


# --- formas ----------------------------------------------------------------------

def test_cada_forma_dibuja_su_figura_y_el_numero():
    assert _kinds(step_primitives(S, 1.0)) == ["PCircle", "PText"]
    assert _kinds(step_primitives(replace(S, shape=StepShape.SQUARE), 1.0)) == ["PRect", "PText"]
    assert _kinds(step_primitives(replace(S, shape=StepShape.ROUNDED), 1.0)) == ["PRect", "PText"]
    assert _kinds(step_primitives(replace(S, shape=StepShape.DIAMOND), 1.0)) == ["PPolygon", "PText"]


def test_cuadrado_y_cuadrado_redondeado():
    cuadrado = step_primitives(replace(S, shape=StepShape.SQUARE), 1.0)[0]
    assert cuadrado.rect == Rect(80, 80, 40, 40) and cuadrado.rx == 0 and cuadrado.fill == style.CARD_FILL
    redondeado = step_primitives(replace(S, shape=StepShape.ROUNDED), 1.0)[0]
    assert redondeado.rect == Rect(80, 80, 40, 40) and redondeado.rx == pytest.approx(20 * style.STEP_ROUNDED_CORNER)


def test_el_rombo_tiene_cuatro_puntas_centradas():
    rombo = step_primitives(replace(S, shape=StepShape.DIAMOND), 1.0)[0]
    d = 20 * style.STEP_DIAMOND_FACTOR
    assert rombo.points == ((100, 100 - d), (100 + d, 100), (100, 100 + d), (100 - d, 100))
    assert rombo.fill == style.CARD_FILL and rombo.stroke == style.GOLD
    assert step_extent(replace(S, shape=StepShape.DIAMOND), 1.0) == d and step_extent(S, 1.0) == 20


# --- colores ---------------------------------------------------------------------

def test_borde_relleno_y_numero_tienen_colores_independientes():
    s = replace(S, color="#111111", fill_color="#222222", number_color="#333333")
    figura, texto = step_primitives(s, 1.0)
    assert (figura.stroke, figura.fill, texto.color) == ("#111111", "#222222", "#333333")


def test_el_numero_sigue_al_borde_si_no_tiene_color_propio():
    figura, texto = step_primitives(replace(S, color="#111111"), 1.0)
    assert texto.color == "#111111"
    assert step_primitives(S, 1.0, Palette(step="#445566"))[1].color == "#445566"
    assert step_primitives(replace(S, number_color="#333333"), 1.0, Palette(step="#445566"))[1].color == "#333333"


# --- tamano, numero y grosor -------------------------------------------------------

def test_el_tamano_escala_la_figura_y_el_numero_automatico():
    figura, texto = step_primitives(replace(S, size=30.0), 1.0)
    assert figura.r == 30.0 and texto.size == pytest.approx(25.5)   # 30 * 17/20
    assert step_primitives(replace(S, size=30.0), 2.0)[1].size == pytest.approx(51.0)


def test_el_tamano_del_numero_propio_manda_y_escala_con_el_trazo():
    texto = step_primitives(replace(S, number_size=40.0), 1.5)[1]
    assert texto.size == 60.0


def test_el_grosor_del_borde():
    assert step_primitives(replace(S, border_width=6.0), 2.0)[0].width == 12.0


# --- resplandor ----------------------------------------------------------------------

@pytest.mark.parametrize("shape,kind", [
    (StepShape.CIRCLE, PCircle), (StepShape.SQUARE, PRect), (StepShape.ROUNDED, PRect), (StepShape.DIAMOND, PPolygon),
])
def test_el_resplandor_sigue_la_forma_y_va_debajo(shape, kind):
    prims = step_primitives(replace(S, shape=shape, glow=True), 1.0)
    rings = prims[:len(style.GLOW_RINGS)]
    assert len(prims) == len(style.GLOW_RINGS) + 2
    assert all(isinstance(r, kind) and r.stroke == style.GLOW_GOLD and r.opacity < 0.6 for r in rings)
    assert isinstance(prims[-1], PText)


def test_el_color_del_resplandor_es_el_propio_o_el_de_la_paleta():
    assert step_primitives(replace(S, glow=True), 1.0, Palette(glow="#112233"))[0].stroke == "#112233"
    assert step_primitives(replace(S, glow=True, glow_color="#AABBCC"), 1.0)[0].stroke == "#AABBCC"


def test_los_anillos_crecen_hacia_afuera():
    radios = [p.r for p in step_primitives(replace(S, glow=True), 1.0)[:9]]
    assert radios == sorted(radios) and radios[0] >= 20


def test_el_resplandor_del_paso_pide_margen_en_el_borde():
    paso = StepBadge("s", (25.0, 100.0), 1, glow=True)
    doc = lambda s: AnnotationDoc(Path("x.png"), (400, 300), [s], style_scale=1.0)   # noqa: E731
    assert required_padding(doc(paso)) > required_padding(doc(replace(paso, glow=False)))


# --- seleccion -----------------------------------------------------------------------

def test_clic_en_cada_forma():
    esquina = (100 + 17, 100 + 17)   # dentro del cuadrado y fuera del circulo y del rombo
    assert edit.hit_test([S], esquina, 2, 1.0) is None
    assert edit.hit_test([replace(S, shape=StepShape.SQUARE)], esquina, 2, 1.0) == "s"
    assert edit.hit_test([replace(S, shape=StepShape.ROUNDED)], esquina, 2, 1.0) == "s"
    assert edit.hit_test([replace(S, shape=StepShape.DIAMOND)], esquina, 2, 1.0) is None
    punta = (100 + 24, 100)          # fuera del circulo, dentro del rombo (semidiagonal 25)
    assert edit.hit_test([S], punta, 2, 1.0) is None
    assert edit.hit_test([replace(S, shape=StepShape.DIAMOND)], punta, 2, 1.0) == "s"


def test_el_tamano_cambia_la_zona_de_clic_y_las_cajas():
    grande = replace(S, size=40.0)
    assert edit.hit_test([grande], (100 + 35, 100), 2, 1.0) == "s"
    assert item_bounds(grande, 1.0) == Rect(60, 60, 80, 80)
    assert edit.selection_rect(replace(S, shape=StepShape.DIAMOND), 1.0) == Rect(75, 75, 50, 50)


def test_mover_un_paso_conserva_su_estilo():
    estilo = replace(S, shape=StepShape.DIAMOND, size=30.0, glow=True, fill_color="#123456")
    assert edit.move_item(estilo, 10, 5) == replace(estilo, center=(110.0, 105.0))


# --- archivo ---------------------------------------------------------------------------

def test_el_estilo_del_paso_se_guarda_y_se_recupera():
    s = StepBadge("s", (10.0, 20.0), 7, "#111111", StepShape.ROUNDED, "#222222", "#333333", 31.5, 22.0, 4.0, True, "#444444")
    assert item_from_dict(item_to_dict(s)) == s
    assert item_from_dict(item_to_dict(S)) == S


def test_un_proyecto_viejo_del_paso_abre_con_el_estilo_de_siempre():
    data = {"type": "step", "id": "s", "center": [10, 20], "number": 2, "color": None}
    s = item_from_dict(data)
    assert (s.shape, s.size, s.border_width, s.number_size, s.glow) == (StepShape.CIRCLE, 20.0, 2.5, None, False)


@pytest.mark.parametrize("key,bad,field,expected", [
    ("shape", "estrella", "shape", StepShape.CIRCLE),
    ("size", 0, "size", style.STEP_RADIUS), ("size", 999, "size", style.STEP_RADIUS),
    ("size", "x", "size", style.STEP_RADIUS), ("size", True, "size", style.STEP_RADIUS),
    ("number_size", 1, "number_size", None), ("number_size", "x", "number_size", None),
    ("border_width", 0, "border_width", style.STEP_STROKE), ("border_width", 50, "border_width", style.STEP_STROKE),
    ("fill_color", "rojo", "fill_color", None), ("number_color", 5, "number_color", None),
])
def test_un_dato_invalido_del_paso_usa_el_de_fabrica(key, bad, field, expected):
    data = item_to_dict(S)
    data[key] = bad
    assert getattr(item_from_dict(data), field) == expected


# --- interfaz ---------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication

from ui.annotate.controller import Tool
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
    t.doc.items.append(StepBadge("a1", (400.0, 250.0), 1))
    t.controller.select("a1")
    QApplication.processEvents()
    return t


def _step(tab):
    return tab.controller.selected_item()


def _reset_btn(control):
    return control.parentWidget().layout().itemAt(1).widget()


def test_el_panel_ofrece_las_cuatro_formas_y_cambia_la_forma(tab):
    combo = tab.panel._step_shape
    assert [combo.itemData(i) for i in range(combo.count())] == ["circle", "square", "rounded", "diamond"]
    combo.setCurrentIndex(combo.findData(StepShape.DIAMOND.value))
    assert _step(tab).shape is StepShape.DIAMOND
    tab.controller.undo()
    assert _step(tab).shape is StepShape.CIRCLE and combo.currentData() == "circle"


def test_los_tres_colores_se_cambian_por_separado_y_muestran_su_valor_de_fabrica(tab):
    p = tab.panel
    assert p._step_fill._picker.hex_color().upper() == style.CARD_FILL.upper()
    assert p._step_color._picker.hex_color().upper() == style.GOLD.upper()
    assert p._step_number_color._picker.hex_color().upper() == style.GOLD.upper()   # el numero sigue al borde
    p._step_fill._on_picked("#222222")
    p._step_number_color._on_picked("#333333")
    p._step_color._on_picked("#111111")
    s = _step(tab)
    assert (s.color, s.fill_color, s.number_color) == ("#111111", "#222222", "#333333")
    p._step_fill.changed.emit(None)    # volver al de marca
    assert _step(tab).fill_color is None


def test_el_numero_sin_color_propio_sigue_al_borde_en_el_panel(tab):
    p = tab.panel
    p._step_color._on_picked("#111111")
    assert p._step_number_color._picker.hex_color().lower() == "#111111"


def test_tamano_del_paso_y_del_numero_auto(tab):
    p = tab.panel
    p._step_size.setValue(32.0)
    assert _step(tab).size == 32.0
    p._step_number_size.setValue(24.0)
    assert _step(tab).number_size == 24.0
    p._step_number_size.setValue(0.0)     # Auto
    assert _step(tab).number_size is None
    p._step_number_size.setValue(2.0)     # por debajo del minimo: se sube al minimo
    assert _step(tab).number_size == style.MIN_NUMBER_SIZE
    assert p._step_number_size.specialValueText() == "Auto"


def test_grosor_y_resplandor_del_paso(tab):
    p = tab.panel
    p._step_stroke.setValue(6.0)
    assert _step(tab).border_width == 6.0
    assert p._step_form.isRowVisible(p._step_glow_color) is False
    p._step_glow.setChecked(True)
    assert _step(tab).glow and p._step_form.isRowVisible(p._step_glow_color) is True
    p._step_glow_color._on_picked("#AABBCC")
    assert _step(tab).glow_color == "#AABBCC"


def test_restablecer_forma_tamano_grosor_y_numero(tab):
    p = tab.panel
    p._step_shape.setCurrentIndex(p._step_shape.findData(StepShape.SQUARE.value))
    p._step_size.setValue(50.0)
    p._step_stroke.setValue(8.0)
    p._step_number_size.setValue(30.0)
    for control in (p._step_shape, p._step_size, p._step_stroke, p._step_number_size):
        assert _reset_btn(control).isEnabled()
        _reset_btn(control).click()
        assert not _reset_btn(control).isEnabled()
    s = _step(tab)
    assert (s.shape, s.size, s.border_width, s.number_size) == (StepShape.CIRCLE, 20.0, 2.5, None)


def test_el_paso_con_estilo_se_exporta(tab, tmp_path):
    tab.controller.set_style_scale(1.0)
    p = tab.panel
    p._step_shape.setCurrentIndex(p._step_shape.findData(StepShape.SQUARE.value))
    p._step_fill._on_picked("#FF0000")
    p._step_number_color._on_picked("#FF0000")   # el numero tambien rojo: el centro es todo relleno
    p._step_size.setValue(30.0)
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    img = Image.open(out).convert("RGB")
    assert img.getpixel((415, 235)) == (255, 0, 0)       # esquina del cuadrado (dentro de 30 px, fuera de un circulo de 20)
    assert img.getpixel((400 + 45, 250)) == (255, 255, 255)


def test_los_pasos_nuevos_salen_con_el_estilo_de_siempre_y_la_herramienta_sigue(tab):
    tab.tool_buttons[Tool.STEP].click()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent

    for pt in ((100.0, 100.0), (200.0, 100.0)):
        pos = tab.canvas.image_to_view(pt)
        QApplication.sendEvent(tab.canvas, QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(tab.canvas, QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    nuevos = [i for i in tab.doc.items if i.id != "a1"]
    assert [i.number for i in nuevos] == [2, 3]
    assert all(i.shape is StepShape.CIRCLE and i.size == 20.0 and not i.glow for i in nuevos)
    assert tab.controller.tool is Tool.STEP
