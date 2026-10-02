import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.annotate.model import Highlight, Magnifier, Marker, Redaction, StepBadge, TextLabel
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
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)


def test_las_herramientas_que_se_repiten_son_todas_menos_texto_y_las_de_vista():
    assert STICKY_TOOLS == {
        Tool.MARKER, Tool.MARKER_PLAIN, Tool.HIGHLIGHT, Tool.ARROW, Tool.LINE, Tool.PEN, Tool.PEN_MARKER, Tool.STEP,
        Tool.REDACT, Tool.LENS, Tool.CHECK, Tool.CROSS, Tool.ICON,
    }
    assert Tool.TEXT not in STICKY_TOOLS and Tool.SELECT not in STICKY_TOOLS and Tool.CROP not in STICKY_TOOLS


@pytest.mark.parametrize("tool,kind", [
    (Tool.MARKER, Marker), (Tool.MARKER_PLAIN, Marker), (Tool.HIGHLIGHT, Highlight),
    (Tool.REDACT, Redaction), (Tool.LENS, Magnifier),
])
def test_dibujar_dos_veces_seguidas_con_un_solo_clic_en_la_herramienta(tab, tool, kind):
    tab.tool_buttons[tool].click()
    drag(tab.canvas, (100, 100), (250, 160))
    assert tab.controller.tool is tool and tab.tool_buttons[tool].isChecked()
    drag(tab.canvas, (100, 300), (250, 360))
    assert [type(i) for i in tab.doc.items] == [kind, kind]
    assert tab.controller.tool is tool
    assert tab.controller.stack.count() == 2


def test_flecha_y_paso_tambien_se_repiten(tab):
    tab.tool_buttons[Tool.ARROW].click()
    drag(tab.canvas, (100, 100), (250, 160))
    drag(tab.canvas, (100, 300), (250, 360))
    assert tab.controller.tool is Tool.ARROW and len(tab.doc.items) == 2
    tab.tool_buttons[Tool.STEP].click()
    for x in (400, 450, 500):
        drag(tab.canvas, (x, 50), (x, 50))
    steps = [i for i in tab.doc.items if isinstance(i, StepBadge)]
    assert [s.number for s in steps] == [1, 2, 3] and tab.controller.tool is Tool.STEP


def test_la_ultima_anotacion_queda_seleccionada_y_su_panel_visible(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (250, 160))
    drag(tab.canvas, (100, 300), (250, 360))
    assert tab.controller.selected_id == tab.doc.items[1].id
    assert tab.panel._title.text() == "Marcador"
    tab.panel._marker_stroke._on_picked("#123456")   # editar la ultima desde el panel, sin salir de la herramienta
    assert tab.doc.items[1].stroke_color == "#123456" and tab.doc.items[0].stroke_color is None
    assert tab.controller.tool is Tool.MARKER


def test_el_texto_no_se_repite_y_vuelve_a_seleccionar(tab):
    tab.tool_buttons[Tool.TEXT].click()
    drag(tab.canvas, (200, 200), (200, 200))
    assert isinstance(tab.doc.items[0], TextLabel)
    assert tab.controller.tool is Tool.SELECT and tab.tool_buttons[Tool.SELECT].isChecked()


def test_esc_sale_de_la_herramienta_y_deja_lo_dibujado_seleccionado(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (250, 160))
    QTest.keyClick(tab.canvas, Qt.Key_Escape)
    assert tab.controller.tool is Tool.SELECT and tab.tool_buttons[Tool.SELECT].isChecked()
    assert tab.controller.selected_id == tab.doc.items[0].id    # sigue seleccionado para editarlo
    QTest.keyClick(tab.canvas, Qt.Key_Escape)
    assert tab.controller.selected_id is None


def test_elegir_otra_herramienta_cambia_de_herramienta(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (250, 160))
    tab.tool_buttons[Tool.ARROW].click()
    assert tab.controller.tool is Tool.ARROW and tab.controller.selected_id is None
    drag(tab.canvas, (100, 300), (250, 360))
    assert [type(i).__name__ for i in tab.doc.items] == ["Marker", "Arrow"]


def test_un_arrastre_minusculo_no_crea_nada_y_no_suelta_la_herramienta(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (102, 101))
    assert tab.doc.items == [] and tab.controller.tool is Tool.MARKER


def test_con_la_herramienta_activa_un_clic_sobre_lo_dibujado_crea_otra_en_vez_de_seleccionar(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (250, 160))
    drag(tab.canvas, (120, 110), (200, 150))   # arrastrar encima del anterior dibuja uno nuevo
    assert len(tab.doc.items) == 2


def test_deshacer_con_la_herramienta_activa_la_conserva(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100, 100), (250, 160))
    drag(tab.canvas, (100, 300), (250, 360))
    tab.controller.undo()
    assert len(tab.doc.items) == 1 and tab.controller.tool is Tool.MARKER


def test_los_tooltips_avisan_de_que_la_herramienta_sigue_activa(tab):
    assert "Esc para salir" in tab.tool_buttons[Tool.MARKER].toolTip()
    assert "Esc para salir" not in tab.tool_buttons[Tool.TEXT].toolTip()
    assert "Esc para salir" not in tab.tool_buttons[Tool.SELECT].toolTip()
