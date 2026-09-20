import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

import math

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate import style
from core.annotate.io import load_doc, save_doc
from core.annotate.model import PenMode, Stroke
from core.annotate.svg import render_bytes
from ui.annotate.controller import Tool
from ui.annotate.panel import _PAGE_STROKE
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


def draw(canvas, points):
    _mouse(canvas, QEvent.MouseButtonPress, points[0])
    for p in points[1:]:
        _mouse(canvas, QEvent.MouseMove, p, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, points[-1], buttons=Qt.NoButton)


def _circle(cx=300, cy=250, r=100, n=120):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _stroke(tab):
    return [i for i in tab.doc.items if isinstance(i, Stroke)]


def test_los_botones_del_lapiz_existen(tab):
    assert Tool.PEN in tab.tool_buttons and Tool.PEN_MARKER in tab.tool_buttons


def test_dibujar_un_circulo_con_el_lapiz_deja_un_trazo_y_un_paso_de_deshacer(tab):
    tab.tool_buttons[Tool.PEN].click()
    draw(tab.canvas, _circle())
    strokes = _stroke(tab)
    assert len(strokes) == 1 and strokes[0].mode is PenMode.PEN
    assert strokes[0].width == style.PEN_WIDTH
    assert 8 <= len(strokes[0].points) < 60          # se simplifico: no se guarda cada punto del mouse
    assert tab.controller.stack.count() == 1
    tab.controller.undo()
    assert not _stroke(tab)
    tab.controller.redo()
    assert len(_stroke(tab)) == 1


def test_el_resaltador_libre_crea_un_trazo_ancho_en_modo_marcador(tab):
    tab.tool_buttons[Tool.PEN_MARKER].click()
    draw(tab.canvas, [(100, 100), (200, 110), (300, 100), (400, 112)])
    (s,) = _stroke(tab)
    assert s.mode is PenMode.MARKER and s.width == style.PEN_MARKER_WIDTH


def test_un_clic_sin_arrastrar_no_deja_trazo(tab):
    tab.tool_buttons[Tool.PEN].click()
    draw(tab.canvas, [(200, 200), (200, 200)])
    assert not _stroke(tab) and tab.controller.stack.count() == 0


def test_la_herramienta_se_repite_y_el_trazo_queda_seleccionado(tab):
    tab.tool_buttons[Tool.PEN].click()
    draw(tab.canvas, [(100, 100), (200, 150), (300, 100)])
    draw(tab.canvas, [(100, 300), (200, 350), (300, 300)])
    assert len(_stroke(tab)) == 2 and tab.controller.tool is Tool.PEN


def test_trazo_con_muchisimos_puntos_se_reduce(tab):
    tab.tool_buttons[Tool.PEN].click()
    pts = [(50 + i * 0.5, 250 + 40 * math.sin(i / 20)) for i in range(1400)]
    draw(tab.canvas, pts)
    (s,) = _stroke(tab)
    assert len(s.points) < 200


# --- panel ------------------------------------------------------------------


def _drawn(tab, mode_tool=Tool.PEN):
    tab.tool_buttons[mode_tool].click()
    draw(tab.canvas, [(100, 100), (200, 160), (300, 100), (400, 170)])
    tab.tool_buttons[Tool.SELECT].click()
    s = _stroke(tab)[0]
    tab.controller.select(s.id)
    QApplication.processEvents()
    return s


def test_el_panel_muestra_la_pagina_del_trazo(tab):
    _drawn(tab)
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_STROKE
    assert p._pen_mode.currentData() == PenMode.PEN.value
    assert p._pen_width.value() == style.PEN_WIDTH
    assert p._pen_opacity.value() == 100


def test_cambiar_grosor_color_y_resplandor_desde_el_panel(tab):
    _drawn(tab)
    p = tab.panel
    assert not p._pen_form.isRowVisible(p._pen_glow_color)
    p._pen_width.setValue(9.0)
    p._pen_glow.setChecked(True)
    QApplication.processEvents()
    s = tab.controller.selected_item()
    assert s.width == 9.0 and s.glow is True
    assert p._pen_form.isRowVisible(p._pen_glow_color)   # el selector del resplandor aparece al activarlo
    tab.controller.edit_selected(_merge=False, color="#00AA00")
    assert tab.controller.selected_item().color == "#00AA00"


def test_cambiar_de_lapiz_a_resaltador_ajusta_grosor_y_opacidad_en_un_paso(tab):
    _drawn(tab)
    before = tab.controller.stack.count()
    tab.panel._pen_mode.setCurrentIndex(tab.panel._pen_mode.findData(PenMode.MARKER.value))
    QApplication.processEvents()
    s = tab.controller.selected_item()
    assert s.mode is PenMode.MARKER and s.width == style.PEN_MARKER_WIDTH
    assert s.opacity == style.HIGHLIGHT_MARKER_OPACITY
    assert tab.controller.stack.count() == before + 1
    tab.controller.undo()
    s = tab.controller.selected_item()
    assert s.mode is PenMode.PEN and s.width == style.PEN_WIDTH and s.opacity == 1.0


def test_entre_los_dos_resaltadores_el_grosor_se_conserva(tab):
    s = _drawn(tab, Tool.PEN_MARKER)
    tab.controller.edit_selected(_merge=False, width=30.0)
    tab.panel._pen_mode.setCurrentIndex(tab.panel._pen_mode.findData(PenMode.OVERLAY.value))
    QApplication.processEvents()
    s = tab.controller.selected_item()
    assert s.mode is PenMode.OVERLAY and s.width == 30.0
    assert s.opacity == style.HIGHLIGHT_OVERLAY_OPACITY


# --- exportar y guardar -----------------------------------------------------


def test_exportar_pinta_el_trazo(tab):
    tab.tool_buttons[Tool.PEN].click()
    draw(tab.canvas, [(100, 200), (300, 200), (500, 200)])
    img = Image.open(io.BytesIO(render_bytes(tab.doc))).convert("RGB")
    assert img.getpixel((300, 200)) != (255, 255, 255)
    assert img.getpixel((300, 300)) == (255, 255, 255)


def test_el_proyecto_guarda_y_recupera_el_trazo(tab, tmp_path):
    _drawn(tab)
    tab.controller.edit_selected(_merge=False, glow=True, width=7.0)
    path = tmp_path / "p.json"
    save_doc(tab.doc, path)
    loaded = load_doc(path)
    (a,) = [i for i in loaded.items if isinstance(i, Stroke)]
    (b,) = _stroke(tab)
    assert a.glow is True and a.width == 7.0 and a.mode is b.mode
    assert len(a.points) == len(b.points)
