"""Panel: Intensidad y Grosor del halo del resplandor, visibles solo con el resplandor activo."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication

from core.annotate.model import Arrow, ArrowSide, Magnifier, Marker, Rect, StepBadge, Stroke
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
    QApplication.processEvents()
    return t


def _select(tab, item):
    tab.doc.items.append(item)
    tab.controller.select(item.id)
    QApplication.processEvents()
    return item


def _casos():
    # (anotacion, atributo de la forma, atributo de los spins, atributo de las filas, casilla que activa el halo)
    return [
        (Marker("m", Rect(100, 100, 100, 60), ArrowSide.NONE, glow=False), "_marker_form", "_marker_glow_spins", "_marker_glow_rows", "_marker_glow"),
        (Arrow("a", (50.0, 50.0), (300.0, 80.0), glow=False), "_arrow_form", "_arrow_glow_spins", "_arrow_glow_rows", "_arrow_glow"),
        (StepBadge("s", (200.0, 200.0), 1, glow=False), "_step_form", "_step_glow_spins", "_step_glow_rows", "_step_glow"),
        (Stroke("p", ((50.0, 50.0), (300.0, 90.0)), glow=False), "_pen_form", "_pen_glow_spins", "_pen_glow_rows", "_pen_glow"),
        (Magnifier("l", Rect(100, 100, 80, 60), (400.0, 200.0), glow=False), "_lens_form", "_lens_glow_spins", "_lens_glow_rows", "_lens_glow"),
    ]


@pytest.mark.parametrize("caso", _casos(), ids=lambda c: type(c[0]).__name__)
def test_los_controles_solo_se_ven_con_el_resplandor_y_cada_cambio_es_un_paso(tab, caso):
    item, form_name, spins_name, rows_name, check_name = caso
    _select(tab, item)
    p = tab.panel
    form, (strength, size), rows = getattr(p, form_name), getattr(p, spins_name), getattr(p, rows_name)
    assert not any(form.isRowVisible(r) for r in rows)
    assert (strength.value(), size.value()) == (100, 100)
    getattr(p, check_name).setChecked(True)
    QApplication.processEvents()
    assert all(form.isRowVisible(r) for r in rows)

    strength.setValue(150)
    size.setValue(250)
    now = tab.controller.selected_item()
    assert (now.glow_strength, now.glow_size) == (1.5, 2.5)

    # restablecer: el boton de la fila devuelve el 100 % en su propio paso
    rows[0].findChildren(type(rows[0].layout().itemAt(1).widget()))[0].click()
    QApplication.processEvents()
    assert tab.controller.selected_item().glow_strength == 1.0 and strength.value() == 100
    tab.controller.undo()
    QApplication.processEvents()
    assert tab.controller.selected_item().glow_strength == 1.5 and strength.value() == 150


def test_la_lupa_muestra_los_controles_tambien_con_solo_el_resplandor_del_conector(tab):
    _select(tab, Magnifier("l", Rect(100, 100, 80, 60), (400.0, 200.0), glow=False, connector_glow=True))
    p = tab.panel
    assert all(p._lens_form.isRowVisible(r) for r in p._lens_glow_rows)
    p._lens_connector.setChecked(False)
    QApplication.processEvents()
    assert not any(p._lens_form.isRowVisible(r) for r in p._lens_glow_rows)


def test_los_valores_ajustados_se_ven_al_seleccionar_otra_anotacion_y_volver(tab):
    m = _select(tab, Marker("m", Rect(100, 100, 100, 60), ArrowSide.NONE, glow=True, glow_strength=0.4, glow_size=2.0))
    s = _select(tab, StepBadge("s", (300.0, 300.0), 1, glow=True))
    p = tab.panel
    assert tuple(sp.value() for sp in p._step_glow_spins) == (100, 100)
    tab.controller.select(m.id)
    QApplication.processEvents()
    assert tuple(sp.value() for sp in p._marker_glow_spins) == (40, 200)
