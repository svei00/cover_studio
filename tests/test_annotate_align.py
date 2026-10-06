"""Alinear y distribuir varias anotaciones (como Photoshop): contra la caja que envuelve a todas; con 3 o mas se reparte el
mismo hueco. Cada accion es UN paso de deshacer."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core.annotate.align import Align, Distribute, align_deltas, bounds, distribute_deltas
from core.annotate.model import AnnotationDoc, Icon, IconKind, Magnifier, Marker, Rect

# --- nucleo ----------------------------------------------------------------------------------------------

BOXES = {"a": Rect(10.0, 10.0, 20.0, 20.0), "b": Rect(50.0, 40.0, 40.0, 10.0), "c": Rect(30.0, 70.0, 10.0, 30.0)}


def test_la_caja_del_conjunto_envuelve_a_todas():
    assert bounds(BOXES) == Rect(10.0, 10.0, 80.0, 90.0)


@pytest.mark.parametrize("mode, esperado", [
    (Align.LEFT, {"b": (-40.0, 0.0), "c": (-20.0, 0.0)}),
    (Align.RIGHT, {"a": (60.0, 0.0), "c": (50.0, 0.0)}),
    (Align.CENTER_H, {"a": (30.0, 0.0), "b": (-20.0, 0.0), "c": (15.0, 0.0)}),   # el centro del conjunto es x = 50
    (Align.TOP, {"b": (0.0, -30.0), "c": (0.0, -60.0)}),
    (Align.BOTTOM, {"a": (0.0, 70.0), "b": (0.0, 50.0)}),
    (Align.MIDDLE_V, {"a": (0.0, 35.0), "b": (0.0, 10.0), "c": (0.0, -30.0)}),   # el centro del conjunto es y = 55
])
def test_cada_alineacion_mueve_lo_justo_contra_la_caja_del_conjunto(mode, esperado):
    deltas = align_deltas(BOXES, mode)
    assert set(deltas) == set(esperado)
    for key, (dx, dy) in esperado.items():
        assert deltas[key] == pytest.approx((dx, dy))


@pytest.mark.parametrize("mode", list(Align))
def test_despues_de_alinear_todas_coinciden_en_ese_borde_o_centro(mode):
    moved = {k: Rect(b.x + align_deltas(BOXES, mode).get(k, (0, 0))[0], b.y + align_deltas(BOXES, mode).get(k, (0, 0))[1], b.w, b.h)
             for k, b in BOXES.items()}
    valor = {
        Align.LEFT: lambda b: b.x, Align.RIGHT: lambda b: b.right, Align.CENTER_H: lambda b: b.center[0],
        Align.TOP: lambda b: b.y, Align.BOTTOM: lambda b: b.bottom, Align.MIDDLE_V: lambda b: b.center[1],
    }[mode]
    assert len({round(valor(b), 6) for b in moved.values()}) == 1
    assert bounds(moved).w <= bounds(BOXES).w + 1e-9 and bounds(moved).h <= bounds(BOXES).h + 1e-9   # el conjunto no crece


def test_con_menos_de_dos_o_ya_alineadas_no_hay_nada_que_mover():
    assert align_deltas({"a": BOXES["a"]}, Align.LEFT) == {} and align_deltas({}, Align.TOP) == {}
    pares = {"a": Rect(0.0, 0.0, 10.0, 10.0), "b": Rect(0.0, 30.0, 10.0, 10.0)}
    assert align_deltas(pares, Align.LEFT) == {}


def test_distribuir_deja_huecos_iguales_y_no_mueve_los_extremos():
    cajas = {"a": Rect(0.0, 0.0, 10.0, 10.0), "b": Rect(15.0, 0.0, 10.0, 10.0), "c": Rect(100.0, 0.0, 10.0, 10.0)}
    deltas = distribute_deltas(cajas, Distribute.HORIZONTAL)
    assert set(deltas) == {"b"}                                         # a y c son los extremos
    # espacio total 110 - 30 de las cajas = 80 de hueco entre 2 huecos: 40 cada uno
    assert deltas["b"] == pytest.approx((40.0 - 15.0 + 10.0, 0.0))     # b queda en x = 50


def test_distribuir_con_cajas_de_distinto_tamano_iguala_el_hueco_no_el_centro():
    cajas = {"a": Rect(0.0, 0.0, 10.0, 10.0), "b": Rect(12.0, 0.0, 40.0, 10.0), "c": Rect(90.0, 0.0, 10.0, 10.0)}
    deltas = distribute_deltas(cajas, Distribute.HORIZONTAL)
    nuevo = {k: b.x + deltas.get(k, (0, 0))[0] for k, b in cajas.items()}
    huecos = [nuevo["b"] - (nuevo["a"] + 10.0), nuevo["c"] - (nuevo["b"] + 40.0)]
    assert huecos[0] == pytest.approx(huecos[1]) and huecos[0] == pytest.approx(20.0)


def test_distribuir_ordena_por_posicion_no_por_el_orden_en_que_se_seleccionaron():
    cajas = {"z": Rect(100.0, 0.0, 10.0, 10.0), "m": Rect(20.0, 0.0, 10.0, 10.0), "a": Rect(0.0, 0.0, 10.0, 10.0), "q": Rect(40.0, 0.0, 10.0, 10.0)}
    deltas = distribute_deltas(cajas, Distribute.HORIZONTAL)
    nuevo = sorted(b.x + deltas.get(k, (0, 0))[0] for k, b in cajas.items())
    huecos = [nuevo[i + 1] - (nuevo[i] + 10.0) for i in range(3)]
    assert nuevo[0] == 0.0 and nuevo[-1] == 100.0 and huecos == pytest.approx([70.0 / 3] * 3)   # (110 - 4 x 10) / 3 huecos


def test_distribuir_en_vertical_y_con_menos_de_tres_o_ya_parejas():
    cajas = {"a": Rect(0.0, 0.0, 10.0, 10.0), "b": Rect(0.0, 20.0, 10.0, 10.0), "c": Rect(0.0, 90.0, 10.0, 10.0)}
    deltas = distribute_deltas(cajas, Distribute.VERTICAL)
    assert set(deltas) == {"b"} and deltas["b"][0] == 0.0 and deltas["b"][1] == pytest.approx(25.0)
    assert distribute_deltas({"a": cajas["a"], "b": cajas["b"]}, Distribute.VERTICAL) == {}
    parejas = {"a": Rect(0.0, 0.0, 10.0, 10.0), "b": Rect(0.0, 50.0, 10.0, 10.0), "c": Rect(0.0, 100.0, 10.0, 10.0)}
    assert distribute_deltas(parejas, Distribute.VERTICAL) == {}


def test_cajas_que_se_solapan_tambien_se_reparten_con_el_mismo_solape():
    cajas = {"a": Rect(0.0, 0.0, 30.0, 10.0), "b": Rect(5.0, 0.0, 30.0, 10.0), "c": Rect(40.0, 0.0, 30.0, 10.0)}
    deltas = distribute_deltas(cajas, Distribute.HORIZONTAL)
    nuevo = {k: b.x + deltas.get(k, (0, 0))[0] for k, b in cajas.items()}
    assert nuevo["b"] - (nuevo["a"] + 30.0) == pytest.approx(nuevo["c"] - (nuevo["b"] + 30.0))


# --- controlador -----------------------------------------------------------------------------------------

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.annotate.controller import EditController  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _columna():
    """Tu caso: cuatro checks y dos cruces en columna, puestos a ojo (un poco desalineados)."""
    return [
        Icon("c1", (100.0, 100.0), IconKind.CHECK), Icon("c2", (104.0, 160.0), IconKind.CHECK),
        Icon("c3", (97.0, 230.0), IconKind.CHECK), Icon("c4", (101.0, 290.0), IconKind.CHECK),
        Icon("x1", (95.0, 390.0), IconKind.CROSS), Icon("x2", (103.0, 450.0), IconKind.CROSS),
    ]


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (1000, 700), _columna(), style_scale=1.0))
    return c


def _centros(c):
    return {i.id: i.center for i in c.doc.items}


def test_centrar_en_horizontal_pone_los_seis_en_una_columna_perfecta_en_un_solo_paso(ctl):
    ctl.select_all()
    ctl.align_selected(Align.CENTER_H)
    xs = {round(c[0], 6) for c in _centros(ctl).values()}
    assert xs == {99.5}                                                  # el centro del conjunto: (75 + 124) / 2 = 99.5
    assert {k: v[1] for k, v in _centros(ctl).items()} == {i.id: i.center[1] for i in _columna()}   # la altura no cambia
    assert ctl.stack.count() == 1 and ctl.stack.undoText() == "Alinear"
    ctl.undo()
    assert _centros(ctl) == {i.id: i.center for i in _columna()}
    ctl.redo()
    assert {round(c[0], 6) for c in _centros(ctl).values()} == {99.5}


def test_alinear_a_la_izquierda_con_iconos_de_distinto_tamano_alinea_sus_bordes(ctl):
    ctl.doc.items[1] = Icon("c2", (104.0, 160.0), IconKind.CHECK, size=30.0)
    ctl.select_many(["c1", "c2", "x1"])
    ctl.align_selected(Align.LEFT)
    lados = {i.id: i.center[0] - i.size for i in ctl.doc.items if i.id in ("c1", "c2", "x1")}
    assert len({round(v, 6) for v in lados.values()}) == 1 and round(next(iter(lados.values())), 6) == 74.0   # el borde mas a la izquierda era 104 - 30


def test_distribuir_en_vertical_deja_el_mismo_hueco_y_no_mueve_el_primero_ni_el_ultimo(ctl):
    ctl.select_all()
    ctl.distribute_selected(Distribute.VERTICAL)
    ys = sorted(c[1] for c in _centros(ctl).values())
    pasos = [round(b - a, 6) for a, b in zip(ys, ys[1:])]
    assert ys[0] == 100.0 and ys[-1] == 450.0 and len(set(pasos)) == 1 and pasos[0] == 70.0
    assert ctl.stack.count() == 1 and ctl.stack.undoText() == "Distribuir"


def test_si_ya_estan_alineadas_no_se_crea_un_paso_vacio(ctl):
    ctl.select_all()
    ctl.align_selected(Align.CENTER_H)
    n = ctl.stack.count()
    ctl.align_selected(Align.CENTER_H)
    assert ctl.stack.count() == n


def test_alinear_y_distribuir_piden_dos_y_tres_como_minimo(ctl):
    ctl.select("c1")
    assert not ctl.can_align() and not ctl.can_distribute()
    ctl.align_selected(Align.LEFT)
    ctl.select_many(["c1", "c2"])
    assert ctl.can_align() and not ctl.can_distribute()
    ctl.distribute_selected(Distribute.VERTICAL)
    assert not ctl.stack.canUndo()
    ctl.select_many(["c1", "c2", "c3"])
    assert ctl.can_distribute()


def test_de_la_lupa_solo_se_mueve_el_lente_y_su_origen_se_queda(ctl):
    lupa = Magnifier("m", Rect(500.0, 100.0, 60.0, 40.0), (700.0, 300.0), 2.0)
    ctl.doc.items.append(lupa)
    ctl.select_many(["c1", "m"])
    ctl.align_selected(Align.CENTER_H)
    despues = ctl.item_by_id("m")
    assert despues.source == lupa.source                                 # la zona ampliada no cambia
    assert despues.lens_center[1] == lupa.lens_center[1] and despues.lens_center[0] != lupa.lens_center[0]
    assert ctl.item_by_id("c1").center[0] == pytest.approx(420.0) and despues.lens_center[0] == pytest.approx(420.0)   # centro del conjunto


def test_el_marcador_se_alinea_por_su_recuadro_y_su_flecha_a_mano_va_con_el(ctl):
    m = Marker("k", Rect(300.0, 500.0, 100.0, 50.0), arrow_start=(300.0, 600.0), arrow_tip=(350.0, 560.0))
    ctl.doc.items.append(m)
    ctl.select_many(["c1", "k"])
    ctl.align_selected(Align.LEFT)
    movido = ctl.item_by_id("k")
    assert movido.rect.x == 80.0                                         # el borde izquierdo del check (100 - 20)
    assert movido.arrow_start == (80.0, 600.0) and movido.arrow_tip == (130.0, 560.0)


def test_alinear_arriba_y_abajo_mueven_en_vertical_sin_tocar_x(ctl):
    ctl.select_many(["c1", "c3", "x2"])
    ctl.align_selected(Align.TOP)
    assert {i.id: i.center[0] for i in ctl.selected_items()} == {"c1": 100.0, "c3": 97.0, "x2": 103.0}
    assert {round(i.center[1], 6) for i in ctl.selected_items()} == {100.0}
    ctl.align_selected(Align.BOTTOM)                                     # ya estan arriba: bajan todas a la misma linea
    assert len({round(i.center[1] + i.size, 6) for i in ctl.selected_items()}) == 1


# --- panel -----------------------------------------------------------------------------------------------

def test_el_panel_tiene_los_ocho_botones_con_icono_y_ayuda(qapp):
    from ui.annotate.tab import AnnotateTab

    p = AnnotateTab().panel
    assert set(p._align_buttons) == set(Align) and set(p._distribute_buttons) == set(Distribute)
    for button in [*p._align_buttons.values(), *p._distribute_buttons.values()]:
        assert not button.icon().isNull() and len(button.toolTip()) > 10


def test_los_botones_alinean_la_seleccion_y_distribuir_se_activa_con_tres(qapp, tmp_path):
    from PIL import Image

    from ui.annotate.panel import _PAGE_MULTI
    from ui.annotate.tab import AnnotateTab

    Image.new("RGB", (800, 600), (255, 255, 255)).save(tmp_path / "cap.png")
    tab = AnnotateTab()
    tab.resize(1400, 800)
    tab.show()
    QApplication.processEvents()
    tab.load_capture(tmp_path / "cap.png")
    tab.doc.items.extend(_columna())
    p = tab.panel
    tab.controller.select_many(["c1", "c2"])
    QApplication.processEvents()
    assert p._pages.currentIndex() == _PAGE_MULTI
    assert all(b.isEnabled() for b in p._align_buttons.values()) and not any(b.isEnabled() for b in p._distribute_buttons.values())
    tab.controller.select_many(["c1", "c2", "c3"])
    QApplication.processEvents()
    assert all(b.isEnabled() for b in p._distribute_buttons.values())
    p._align_buttons[Align.CENTER_H].click()
    assert len({round(i.center[0], 6) for i in tab.controller.selected_items()}) == 1
    assert tab.controller.stack.count() == 1
