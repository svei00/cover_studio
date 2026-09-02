import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.annotate import style
from core.annotate.model import Highlight, HighlightMode
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
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)


@pytest.fixture
def hl(tab):
    tab.tool_buttons[Tool.HIGHLIGHT].click()
    drag(tab.canvas, (100, 100), (300, 140))
    QApplication.processEvents()
    return tab.doc.items[0]


def test_el_boton_resaltar_existe_y_dibuja_un_resaltador(tab, hl):
    assert isinstance(hl, Highlight)
    assert (hl.rect.x, hl.rect.y) == pytest.approx((100, 100), abs=1)
    assert hl.rect.w == pytest.approx(200, abs=1) and hl.color is None and hl.mode is HighlightMode.MARKER
    assert tab.controller.selected_id == hl.id and tab.controller.tool is Tool.SELECT
    assert tab.panel._title.text() == "Resaltador"
    assert tab.controller.stack.count() == 1


def test_un_arrastre_minusculo_no_crea_nada(tab):
    tab.tool_buttons[Tool.HIGHLIGHT].click()
    drag(tab.canvas, (100, 100), (103, 102))
    assert tab.doc.items == []


def test_una_muestra_estandar_cambia_el_color_en_un_paso(tab, hl):
    pasos = tab.controller.stack.count()
    verde = style.HIGHLIGHT_SWATCHES[1][1]
    tab.panel._hl_swatches.colorPicked.emit(verde)
    assert tab.controller.selected_item().color == verde
    assert tab.controller.stack.count() == pasos + 1
    tab.controller.undo()
    assert tab.controller.selected_item().color is None


def test_las_muestras_se_pueden_pulsar_con_el_mouse(tab, hl):
    boton = tab.panel._hl_swatches._buttons[style.HIGHLIGHT_SWATCHES[2][1].upper()]
    QTest.mouseClick(boton, Qt.LeftButton)
    assert tab.controller.selected_item().color == style.HIGHLIGHT_SWATCHES[2][1]


def test_la_muestra_vigente_se_marca_y_con_color_personalizado_ninguna(tab, hl):
    estilo = lambda color: tab.panel._hl_swatches._buttons[color.upper()].styleSheet()  # noqa: E731
    assert "2px solid #FFFFFF" in estilo(style.HIGHLIGHT_YELLOW)           # el de la paleta
    tab.panel._hl_color._on_picked("#123456")                               # personalizado
    assert tab.controller.selected_item().color == "#123456"
    assert all("2px" not in b.styleSheet() for b in tab.panel._hl_swatches._buttons.values())


def test_el_color_por_defecto_sale_de_la_paleta_del_documento(tab, hl):
    tab.controller.set_palette(replace(tab.doc.palette, highlight="#7CFC00"))
    assert "2px solid #FFFFFF" in tab.panel._hl_swatches._buttons["#7CFC00"].styleSheet()
    assert tab.panel._hl_color.hex_color().upper() == "#7CFC00"


def test_cambiar_de_modo_ajusta_la_intensidad_en_un_solo_paso(tab, hl):
    pasos = tab.controller.stack.count()
    combo = tab.panel._hl_mode
    combo.setCurrentIndex(combo.findData(HighlightMode.OVERLAY.value))
    item = tab.controller.selected_item()
    assert (item.mode, item.opacity) == (HighlightMode.OVERLAY, style.HIGHLIGHT_OVERLAY_OPACITY)
    assert tab.panel._hl_opacity.value() == 50
    assert tab.controller.stack.count() == pasos + 1
    tab.controller.undo()
    assert tab.controller.selected_item().mode is HighlightMode.MARKER
    assert tab.panel._hl_opacity.value() == 100


def test_intensidad_y_esquinas_desde_el_panel(tab, hl):
    tab.panel._hl_opacity.setValue(60)
    tab.panel._hl_radius.setValue(8.0)
    item = tab.controller.selected_item()
    assert item.opacity == pytest.approx(0.6) and item.radius == 8.0


def test_restablecer_modo_intensidad_y_esquinas(tab, hl):
    panel = tab.panel
    form = panel._hl_opacity.parentWidget().parentWidget().layout()

    def reset_btn(control):
        return control.parentWidget().layout().itemAt(1).widget()

    assert not reset_btn(panel._hl_mode).isEnabled() and not reset_btn(panel._hl_opacity).isEnabled()
    panel._hl_mode.setCurrentIndex(panel._hl_mode.findData(HighlightMode.OVERLAY.value))
    panel._hl_opacity.setValue(70)
    panel._hl_radius.setValue(12.0)
    assert reset_btn(panel._hl_mode).isEnabled()
    reset_btn(panel._hl_radius).click()
    assert tab.controller.selected_item().radius == style.HIGHLIGHT_RADIUS
    # en modo translucido la intensidad de fabrica es la de ese modo
    reset_btn(panel._hl_opacity).click()
    assert tab.controller.selected_item().opacity == style.HIGHLIGHT_OVERLAY_OPACITY
    reset_btn(panel._hl_mode).click()
    item = tab.controller.selected_item()
    assert (item.mode, item.opacity) == (HighlightMode.MARKER, style.HIGHLIGHT_MARKER_OPACITY)
    assert not reset_btn(panel._hl_mode).isEnabled()


def test_mover_redimensionar_y_borrar(tab, hl):
    tab.controller.nudge(10, 0)
    assert tab.controller.selected_item().rect.x == pytest.approx(hl.rect.x + 10)
    tab.controller.delete_selected()
    assert tab.doc.items == []


def test_exportar_con_resaltador_y_reabrir_el_proyecto(tab, hl, tmp_path):
    tab.panel._hl_swatches.colorPicked.emit(style.HIGHLIGHT_SWATCHES[3][1])
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    px = Image.open(out).convert("RGB").getpixel((200, 120))
    assert px == pytest.approx((255, 165, 0), abs=3)   # naranja sobre blanco (multiplicar)
    assert tab.save_project()
    tab2 = AnnotateTab()
    tab2.load_capture(tmp_path / "cap.png")
    assert tab2.doc.items[0].color == style.HIGHLIGHT_SWATCHES[3][1]
