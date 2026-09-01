import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate import style
from core.annotate.palette import BRAND_PALETTE, Palette
from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab

GREEN, BLUE, PINK = "#00aa00", "#2255dd", "#ff66aa"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    Image.new("RGB", (800, 500), (40, 60, 90)).save(tmp_path / "cap.png")
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def mdrag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton)


def draw(tab, tool=Tool.MARKER, a=(300.0, 200.0), b=(500.0, 280.0)):
    tab.tool_buttons[tool].click()
    mdrag(tab.canvas, a, b)


# --- controlador ----------------------------------------------------------------

def test_set_palette_se_deshace_y_ensucia(tab):
    assert not tab.is_dirty()
    tab.controller.set_palette(Palette(marker=GREEN))
    assert tab.doc.palette.marker == GREEN and tab.is_dirty()
    tab.controller.undo()
    assert tab.doc.palette == BRAND_PALETTE and not tab.is_dirty()


def test_cada_cambio_de_paleta_es_su_propio_paso(tab):
    for color in ("#111111", "#222222", "#333333"):
        tab.controller.set_palette(Palette(marker=color))
    assert tab.doc.palette.marker == "#333333" and tab.controller.stack.count() == 3
    tab.controller.undo()
    assert tab.doc.palette.marker == "#222222"  # deshace solo el ultimo, no todos


def test_set_palette_con_la_misma_paleta_no_hace_nada(tab):
    tab.controller.set_palette(BRAND_PALETTE)
    assert not tab.controller.stack.canUndo()


# --- paleta del documento en el panel ------------------------------------------

def test_los_selectores_del_documento_muestran_la_paleta_y_la_editan(tab):
    assert tab.panel._palette_pickers["marker"].hex_color().lower() == style.RED.lower()
    assert tab.panel._palette_pickers["glow"].hex_color().lower() == style.GLOW_GOLD.lower()
    tab.panel._palette_pickers["marker"].set_hex_color(GREEN)  # igual que elegir en el dialogo
    assert tab.doc.palette.marker == GREEN and tab.doc.palette.arrow == style.RED  # solo cambio ese


def test_restaurar_colores_de_marca(tab):
    assert not tab.panel._restore_btn.isEnabled()  # ya son los de marca
    tab.panel._palette_pickers["marker"].set_hex_color(GREEN)
    tab.panel._palette_pickers["glow"].set_hex_color(PINK)
    assert tab.panel._restore_btn.isEnabled()
    tab.panel._restore_btn.click()
    assert tab.doc.palette == BRAND_PALETTE and not tab.panel._restore_btn.isEnabled()
    tab.controller.undo()  # y el restaurar tambien se deshace
    assert tab.doc.palette.marker == GREEN


def test_sin_captura_no_se_muestran_los_colores(qapp):
    assert AnnotateTab().panel._colors_group.isHidden()


# --- colores propios de cada anotacion ---------------------------------------------

def test_un_marcador_nuevo_muestra_los_colores_de_la_paleta_y_sin_boton_de_volver(tab):
    draw(tab)
    p = tab.panel
    assert p._marker_stroke.hex_color().lower() == style.RED.lower()
    assert p._marker_glow_color.hex_color().lower() == style.GLOW_GOLD.lower()
    assert not p._marker_stroke._reset.isEnabled()


def test_elegir_un_color_propio_y_volver_a_la_paleta(tab):
    draw(tab)
    p = tab.panel
    p._marker_stroke.changed.emit(GREEN)  # lo que emite el selector al elegir un color
    assert tab.doc.items[0].stroke_color == GREEN and tab.doc.items[0].arrow_color is None
    assert p._marker_stroke.hex_color().lower() == GREEN and p._marker_stroke._reset.isEnabled()
    p._marker_stroke._reset.click()
    assert tab.doc.items[0].stroke_color is None
    assert p._marker_stroke.hex_color().lower() == style.RED.lower() and not p._marker_stroke._reset.isEnabled()


def test_cada_parte_del_marcador_se_cambia_por_separado(tab):
    draw(tab)
    p = tab.panel
    p._marker_stroke.changed.emit(GREEN)
    p._marker_arrow_color.changed.emit(BLUE)
    p._marker_glow_color.changed.emit(PINK)
    m = tab.doc.items[0]
    assert (m.stroke_color, m.arrow_color, m.glow_color) == (GREEN, BLUE, PINK)


def test_los_colores_propios_sobreviven_a_un_cambio_de_paleta_y_los_demas_la_heredan(tab):
    draw(tab)
    tab.panel._marker_stroke.changed.emit(GREEN)  # propio
    tab.controller.set_palette(Palette(marker=BLUE, glow=PINK))
    tab.controller.select(None)
    tab.controller.select(tab.doc.items[0].id)
    p = tab.panel
    assert p._marker_stroke.hex_color().lower() == GREEN        # el propio no cambia
    assert p._marker_glow_color.hex_color().lower() == PINK     # el heredado sigue a la paleta


def test_flecha_paso_y_lupa_tienen_sus_selectores(tab):
    draw(tab, Tool.ARROW, (100.0, 100.0), (300.0, 100.0))
    tab.panel._arrow_color.changed.emit(GREEN)
    tab.panel._arrow_glow_color.changed.emit(PINK)
    assert (tab.doc.items[0].color, tab.doc.items[0].glow_color) == (GREEN, PINK)

    tab.tool_buttons[Tool.STEP].click()
    mdrag(tab.canvas, (400.0, 100.0), (400.0, 100.0))
    tab.panel._step_color.changed.emit(BLUE)
    assert tab.doc.items[1].color == BLUE

    draw(tab, Tool.LENS, (100.0, 300.0), (180.0, 360.0))
    tab.panel._lens_frame.changed.emit(PINK)
    assert tab.doc.items[2].frame_color == PINK


def test_el_cambio_de_color_de_una_anotacion_se_deshace(tab):
    draw(tab)
    tab.panel._marker_stroke.changed.emit(GREEN)
    tab.controller.undo()
    assert tab.doc.items[0].stroke_color is None


def test_cada_color_elegido_en_una_anotacion_es_su_propio_paso(tab):
    draw(tab)
    tab.panel._marker_stroke.changed.emit(GREEN)
    tab.panel._marker_arrow_color.changed.emit(BLUE)
    tab.controller.undo()
    m = tab.doc.items[0]
    assert m.stroke_color == GREEN and m.arrow_color is None  # solo se deshizo el ultimo color


def test_escribir_texto_sigue_fusionandose_en_un_paso(tab):
    draw(tab, Tool.TEXT, (100.0, 100.0), (100.0, 100.0))
    for texto in ("H", "Ho", "Hola"):
        tab.panel._text_edit.setPlainText(texto)
    tab.controller.undo()
    assert tab.doc.items[0].text == "Texto"  # el texto si se fusiona: es escritura continua


# --- llega a la pantalla y al archivo --------------------------------------------

def _pixel(tab, image_pt):
    img = tab.canvas.grab().toImage()
    v = tab.canvas.image_to_view(image_pt)
    return QColor(img.pixel(int(v.x()), int(v.y())))


def test_el_color_se_ve_en_el_lienzo(tab):
    draw(tab)
    tab.controller.select(None)
    rect = tab.doc.items[0].rect
    borde = (rect.x, rect.y + rect.h / 2)
    rojo = _pixel(tab, borde)
    assert rojo.red() > rojo.green() + 20
    tab.controller.set_palette(Palette(marker=GREEN))
    verde = _pixel(tab, borde)
    assert verde.green() > verde.red() + 40


def test_el_color_llega_al_png_exportado(tab, tmp_path):
    draw(tab)
    tab.controller.set_palette(Palette(marker=GREEN))
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    rect = tab.doc.items[0].rect
    px = Image.open(out).convert("RGB").getpixel((round(rect.x), round(rect.y + rect.h / 2)))
    assert px[1] > px[0] + 40


def test_la_paleta_y_los_colores_propios_sobreviven_a_guardar_y_reabrir(tab, tmp_path):
    draw(tab)
    tab.controller.set_palette(Palette(arrow=BLUE, glow=PINK))
    tab.panel._marker_stroke.changed.emit(GREEN)
    assert tab.save_project()
    guardado = replace(tab.doc.items[0])
    tab.load_capture(tmp_path / "cap.png")
    assert tab.doc.palette == Palette(arrow=BLUE, glow=PINK) and tab.doc.items[0] == guardado
    assert tab.panel._palette_pickers["arrow"].hex_color().lower() == BLUE
