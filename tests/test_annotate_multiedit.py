"""Edicion en grupo: con varias anotaciones del MISMO tipo seleccionadas (Ctrl + clic) el panel muestra las propiedades de ese tipo
y cada cambio se aplica a todas, en UN paso de deshacer. Con tipos mezclados solo se alinea y distribuye."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication

from core.annotate.model import AnnotationDoc, Arrow, ConnectorRoute, Magnifier, Rect, StepBadge, StepShape, TextLabel
from ui.annotate.controller import EditController
from ui.annotate.panel import _PAGE_MULTI, _PAGE_STEP
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _items():
    return [
        StepBadge("s1", (100.0, 100.0), 1),
        StepBadge("s2", (200.0, 100.0), 2),
        StepBadge("s3", (300.0, 100.0), 3),
        Arrow("f1", (100.0, 300.0), (300.0, 300.0)),
        Arrow("f2", (100.0, 400.0), (300.0, 450.0)),
    ]


@pytest.fixture
def ctl(qapp):
    c = EditController()
    c.set_doc(AnnotationDoc(Path("x.png"), (1000, 700), _items(), style_scale=1.0))
    return c


def _steps(c):
    return [c.item_by_id(i) for i in ("s1", "s2", "s3")]


def test_el_objetivo_de_edicion_es_la_principal_si_son_del_mismo_tipo(ctl):
    ctl.select_many(["s1", "s3"])
    assert ctl.selected_item() is None and ctl.edit_target().id == "s3"
    ctl.select_many(["s1", "f1"])
    assert ctl.edit_target() is None                                     # tipos mezclados
    ctl.select("s2")
    assert ctl.edit_target().id == "s2" and ctl.selected_item().id == "s2"
    ctl.select(None)
    assert ctl.edit_target() is None


def test_un_cambio_de_formato_se_aplica_a_todas_las_seleccionadas(ctl):
    ctl.select_many(["s1", "s2", "s3"])
    ctl.edit_selected(_merge=False, shape=StepShape.DIAMOND, color="#112233")
    assert [s.shape for s in _steps(ctl)] == [StepShape.DIAMOND] * 3
    assert [s.color for s in _steps(ctl)] == ["#112233"] * 3
    assert [s.number for s in _steps(ctl)] == [1, 2, 3]                  # lo que no se toco, intacto
    assert [s.center for s in _steps(ctl)] == [(100.0, 100.0), (200.0, 100.0), (300.0, 100.0)]


def test_solo_cambian_las_seleccionadas(ctl):
    ctl.select_many(["s1", "s2"])
    ctl.edit_selected(_merge=False, size=30.0)
    assert [s.size for s in _steps(ctl)] == [30.0, 30.0, 20.0]


def test_es_un_solo_paso_de_deshacer_y_de_rehacer(ctl):
    before = _steps(ctl)
    ctl.select_many(["s1", "s2", "s3"])
    ctl.edit_selected(_merge=False, glow=True)
    assert ctl.stack.count() == 1
    ctl.undo()
    assert _steps(ctl) == before
    ctl.redo()
    assert [s.glow for s in _steps(ctl)] == [True] * 3


def test_no_hace_nada_si_ya_tenian_ese_valor(ctl):
    ctl.select_many(["s1", "s2"])
    ctl.edit_selected(_merge=False, shape=StepShape.CIRCLE)
    assert ctl.stack.count() == 0


def test_ajustes_seguidos_del_mismo_campo_se_fusionan_y_de_distinto_campo_no(ctl):
    ctl.select_many(["s1", "s2", "s3"])
    ctl.edit_selected(size=22.0)
    ctl.edit_selected(size=24.0)
    assert ctl.stack.count() == 1 and [s.size for s in _steps(ctl)] == [24.0] * 3
    ctl.edit_selected(border_width=4.0)
    assert ctl.stack.count() == 2
    ctl.undo()
    assert [s.size for s in _steps(ctl)] == [24.0] * 3 and [s.border_width for s in _steps(ctl)] == [2.5] * 3


def test_con_tipos_mezclados_no_se_edita_nada(ctl):
    ctl.select_many(["s1", "f1"])
    ctl.edit_selected(_merge=False, color="#112233")
    assert ctl.stack.count() == 0 and ctl.item_by_id("s1").color is None


def test_el_codo_se_aplica_a_varias_flechas(ctl):
    ctl.select_many(["f1", "f2"])
    ctl.edit_selected(_merge=False, route=ConnectorRoute.ELBOW)
    assert ctl.item_by_id("f1").route is ctl.item_by_id("f2").route is ConnectorRoute.ELBOW


def test_la_lupa_en_grupo_recoloca_cada_lente_segun_su_propio_origen(ctl):
    ctl.set_doc(AnnotationDoc(Path("x.png"), (1000, 700), [
        Magnifier("l1", Rect(100.0, 100.0, 80.0, 40.0), (400.0, 120.0), 2.0),
        Magnifier("l2", Rect(100.0, 400.0, 80.0, 40.0), (400.0, 420.0), 2.0),
    ], style_scale=1.0))
    ctl.select_many(["l1", "l2"])
    ctl.edit_selected(_merge=False, zoom=3.0)
    assert [ctl.item_by_id(i).zoom for i in ("l1", "l2")] == [3.0, 3.0]
    assert ctl.item_by_id("l1").source == Rect(100.0, 100.0, 80.0, 40.0)


# --- panel -----------------------------------------------------------------------------------------------

@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    Image.new("RGB", (800, 500), (40, 60, 90)).save(tmp_path / "cap.png")
    t.load_capture(tmp_path / "cap.png")
    t.controller.doc.items.extend([
        StepBadge("s1", (100.0, 100.0), 1), StepBadge("s2", (200.0, 100.0), 2),
        TextLabel("t1", (100.0, 300.0), "hola"),
    ])
    return t


def test_el_panel_muestra_las_propiedades_del_tipo_con_el_conteo_y_sin_el_numero(tab):
    p, c = tab.panel, tab.controller
    c.select_many(["s1", "s2"])
    QApplication.processEvents()
    assert p._pages.currentIndex() == _PAGE_STEP and "2 seleccionados" in p._title.text()
    assert p._step_form.isRowVisible(p._step_number) is False            # el numero es de cada paso
    c.select("s1")
    QApplication.processEvents()
    assert "seleccionados" not in p._title.text() and p._step_form.isRowVisible(p._step_number)


def test_cambiar_el_control_del_panel_afecta_a_todas(tab):
    p, c = tab.panel, tab.controller
    c.select_many(["s1", "s2"])
    QApplication.processEvents()
    p._step_size.setValue(30.0)
    assert [c.item_by_id(i).size for i in ("s1", "s2")] == [30.0, 30.0]


def test_tipos_mezclados_siguen_con_la_pagina_de_alinear(tab):
    p, c = tab.panel, tab.controller
    c.select_many(["s1", "t1"])
    QApplication.processEvents()
    assert p._pages.currentIndex() == _PAGE_MULTI
