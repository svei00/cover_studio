import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from dataclasses import replace

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFormLayout, QLabel

from core.annotate import style
from core.annotate.model import ArrowSide, LensShape, Magnifier, Marker, Rect, Redaction, TextAlign, text_label_from_preset
from core.annotate.palette import BRAND_PALETTE
from ui.annotate.panel import RESET_TIP, _ResetLabel
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
    QApplication.processEvents()
    return t


def _select(tab, item):
    tab.doc.items.append(item)
    tab.controller.select(item.id)
    QApplication.processEvents()
    return item


def _lens(**kw):
    kw.setdefault("shape", LensShape.ROUNDED)
    return Magnifier("a1", Rect(100, 100, 80, 60), (400.0, 200.0), 2.0, **kw)


def _row(form: QFormLayout, control):
    """(etiqueta, boton de restablecer) de la fila cuyo control es `control`."""
    container = control.parentWidget()
    return form.labelForField(container), container.findChild(type(container.layout().itemAt(1).widget()))


def _dclick(label):
    QTest.mouseDClick(label, Qt.LeftButton)


def _lens_row(tab, control):
    return _row(tab.panel._lens_form, control)


# --- boton ----------------------------------------------------------------

def test_el_boton_se_activa_solo_si_el_valor_no_es_el_de_fabrica(tab):
    _select(tab, _lens())
    _label, button = _lens_row(tab, tab.panel._lens_zoom)
    assert not button.isEnabled()
    tab.panel._lens_zoom.setValue(3.5)
    assert button.isEnabled()
    button.click()
    assert tab.controller.selected_item().zoom == 2.0
    assert not button.isEnabled()
    assert tab.panel._lens_zoom.value() == 2.0   # el control tambien lo refleja


def test_restablecer_es_su_propio_paso_de_deshacer(tab):
    _select(tab, _lens())
    _label, button = _lens_row(tab, tab.panel._lens_zoom)
    tab.panel._lens_zoom.setValue(3.5)
    button.click()
    assert tab.controller.selected_item().zoom == 2.0
    tab.controller.undo()   # deshace SOLO el restablecer: vuelve a 3.5 (por si te equivocaste)
    assert tab.controller.selected_item().zoom == 3.5
    tab.controller.undo()
    assert tab.controller.selected_item().zoom == 2.0
    tab.controller.redo()
    tab.controller.redo()
    assert tab.controller.selected_item().zoom == 2.0


# --- doble clic -----------------------------------------------------------

def test_doble_clic_en_la_etiqueta_restablece(tab):
    _select(tab, _lens(frame_width=9.0, corner=0.4))
    label, _button = _lens_row(tab, tab.panel._lens_frame_width)
    assert isinstance(label, _ResetLabel) and label.toolTip() == RESET_TIP
    _dclick(label)
    assert tab.controller.selected_item().frame_width == style.DEFAULT_LENS_FRAME_WIDTH
    corner_label, _ = _lens_row(tab, tab.panel._lens_corner)
    _dclick(corner_label)
    assert tab.controller.selected_item().corner == style.DEFAULT_LENS_CORNER


def test_un_clic_simple_no_restablece(tab):
    _select(tab, _lens(frame_width=9.0))
    label, _button = _lens_row(tab, tab.panel._lens_frame_width)
    QTest.mouseClick(label, Qt.LeftButton)
    assert tab.controller.selected_item().frame_width == 9.0


def test_restablecer_la_forma_y_el_grosor(tab):
    _select(tab, _lens(shape=LensShape.ELLIPSE))
    label, button = _lens_row(tab, tab.panel._lens_shape)
    assert button.isEnabled()
    button.click()
    assert tab.controller.selected_item().shape is LensShape.CIRCLE


# --- otros tipos ----------------------------------------------------------

def test_lado_de_la_flecha_del_marcador(tab):
    _select(tab, Marker("a1", Rect(100, 100, 80, 60), ArrowSide.LEFT))
    label, button = _row(tab.panel._marker_arrow.parentWidget().parentWidget().layout(), tab.panel._marker_arrow)
    assert button.isEnabled()
    _dclick(label)
    assert tab.controller.selected_item().arrow is ArrowSide.AUTO
    assert not button.isEnabled()


def test_tamano_y_alineacion_del_texto(tab):
    _select(tab, replace(text_label_from_preset("a1", (50.0, 50.0), "Hola"), size=60.0, align=TextAlign.CENTER))
    form = tab.panel._text_size.parentWidget().parentWidget().layout()
    size_label, size_btn = _row(form, tab.panel._text_size)
    align_label, align_btn = _row(form, tab.panel._text_align)
    assert size_btn.isEnabled() and align_btn.isEnabled()
    _dclick(size_label)
    _dclick(align_label)
    item = tab.controller.selected_item()
    assert item.size == 28.0 and item.align is TextAlign.LEFT


def test_el_bloque_del_pixelado_vuelve_al_que_corresponde_a_la_escala(tab):
    tab.controller.set_style_scale(2.0)
    _select(tab, Redaction("a1", Rect(100, 100, 80, 60), 50))
    form = tab.panel._redaction_block.parentWidget().parentWidget().layout()
    label, button = _row(form, tab.panel._redaction_block)
    assert button.isEnabled()
    _dclick(label)
    assert tab.controller.selected_item().block == 24   # 12 * escala 2


# --- documento y colores --------------------------------------------------

def test_margen_y_escala_del_documento(tab):
    panel = tab.panel
    form = panel._padding_spin.parentWidget().parentWidget().layout()
    pad_label, pad_btn = _row(form, panel._padding_spin)
    scale_label, scale_btn = _row(form, panel._scale_spin)
    assert not pad_btn.isEnabled() and not scale_btn.isEnabled()   # margen 0 y escala automatica
    tab.controller.set_padding(40)
    tab.controller.set_style_scale(1.5)
    assert pad_btn.isEnabled() and scale_btn.isEnabled()
    _dclick(pad_label)
    _dclick(scale_label)
    assert tab.doc.padding == 0 and tab.doc.style_scale is None


def test_doble_clic_en_el_color_de_una_anotacion_vuelve_al_de_la_paleta(tab):
    _select(tab, _lens(frame_color="#112233"))
    label = tab.panel._lens_form.labelForField(tab.panel._lens_frame)
    assert isinstance(label, _ResetLabel)
    _dclick(label)
    assert tab.controller.selected_item().frame_color is None


def test_doble_clic_en_un_color_de_la_paleta_vuelve_al_de_marca(tab):
    tab.controller.set_palette(replace(tab.doc.palette, glow="#112233"))
    group_form = tab.panel._colors_group.layout()
    labels = [group_form.itemAt(i, QFormLayout.LabelRole).widget() for i in range(group_form.rowCount())
              if group_form.itemAt(i, QFormLayout.LabelRole)]
    glow_label = next(w for w in labels if isinstance(w, QLabel) and w.text() == "Resplandor")
    _dclick(glow_label)
    assert tab.doc.palette.glow == BRAND_PALETTE.glow
