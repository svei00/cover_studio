"""Iconos en la interfaz: botones Check / Cruz / Icono (con menu), colocacion repetida, panel de propiedades y que los
iconos nuevos hereden el ultimo estilo elegido."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate import style
from core.annotate.io import load_doc, save_doc
from core.annotate.model import Icon, IconKind, IconStyle
from ui.annotate.controller import STICKY_TOOLS, Tool
from ui.annotate.panel import _PAGE_ICON
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1400, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _click(canvas, image_pt):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(canvas, QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def _icons(tab):
    return [i for i in tab.doc.items if isinstance(i, Icon)]


# --- botones ---------------------------------------------------------------------------------------------

def test_hay_botones_de_check_cruz_e_icono_y_las_tres_herramientas_se_repiten(tab):
    for tool, text in ((Tool.CHECK, "Check"), (Tool.CROSS, "Cruz"), (Tool.ICON, "Icono")):
        button = tab.tool_buttons[tool]
        assert button.text() == text and button.isEnabled() and not button.icon().isNull()
        assert tool in STICKY_TOOLS and "Esc" in button.toolTip()


def test_el_menu_de_icono_trae_los_otros_seis_y_con_su_miniatura(tab):
    assert set(tab.icon_actions) == {IconKind.WARNING, IconKind.INFO, IconKind.QUESTION, IconKind.STAR, IconKind.PLUS, IconKind.MINUS}
    assert all(not action.icon().isNull() for action in tab.icon_actions.values())
    assert tab.tool_buttons[Tool.ICON].menu() is not None


# --- colocar ---------------------------------------------------------------------------------------------

def test_el_check_se_coloca_con_un_clic_y_sigue_activo_para_el_siguiente(tab):
    tab.tool_buttons[Tool.CHECK].click()
    _click(tab.canvas, (100.0, 100.0))
    _click(tab.canvas, (300.0, 100.0))
    check, otro = _icons(tab)
    assert (check.kind, check.style) == (IconKind.CHECK, IconStyle.SEAL)
    assert check.center == pytest.approx((100.0, 100.0)) and otro.center == pytest.approx((300.0, 100.0))   # pantalla -> imagen: flotantes
    assert otro.id != check.id and tab.controller.tool is Tool.CHECK
    assert tab.controller.selected_id == otro.id
    tab.controller.undo()
    assert len(_icons(tab)) == 1                                       # un clic = un paso de deshacer


def test_la_cruz_se_coloca_como_cruz(tab):
    tab.tool_buttons[Tool.CROSS].click()
    _click(tab.canvas, (150.0, 200.0))
    assert [i.kind for i in _icons(tab)] == [IconKind.CROSS]


def test_la_herramienta_icono_usa_el_icono_elegido_en_el_menu_y_lo_recuerda(tab):
    tab.tool_buttons[Tool.ICON].click()
    _click(tab.canvas, (100.0, 100.0))
    assert _icons(tab)[-1].kind is IconKind.WARNING                    # el de arranque
    tab.icon_actions[IconKind.STAR].trigger()
    assert tab.controller.tool is Tool.ICON and tab.controller.icon_kind is IconKind.STAR
    assert tab.tool_buttons[Tool.ICON].isChecked()
    _click(tab.canvas, (200.0, 100.0))
    _click(tab.canvas, (300.0, 100.0))
    assert [i.kind for i in _icons(tab)] == [IconKind.WARNING, IconKind.STAR, IconKind.STAR]


# --- panel -----------------------------------------------------------------------------------------------

def _select_new(tab, tool=Tool.CHECK):
    tab.tool_buttons[tool].click()
    _click(tab.canvas, (200.0, 200.0))
    tab.tool_buttons[Tool.SELECT].click()
    icon = _icons(tab)[-1]
    tab.controller.select(icon.id)
    QApplication.processEvents()
    return icon


def test_el_panel_muestra_la_pagina_del_icono_con_sus_valores(tab):
    _select_new(tab)
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_ICON and p._title.text() == "Icono"
    assert p._icon_kind.currentData() == "check" and p._icon_style.currentData() == "seal"
    assert p._icon_color.hex_color().upper() == style.ICON_COLORS["check"].upper()
    assert p._icon_glyph_color.hex_color().upper() == style.ICON_LIGHT
    assert p._icon_size.value() == style.ICON_RADIUS and p._icon_ring.isChecked() and not p._icon_glow.isChecked()


def test_cambiar_el_icono_es_un_paso_de_deshacer_y_los_de_check_y_cruz_no_cambian_el_de_la_herramienta(tab):
    _select_new(tab)
    p = tab.panel
    pasos = tab.controller.stack.count()
    p._icon_kind.setCurrentIndex(p._icon_kind.findData("info"))
    assert tab.controller.selected_item().kind is IconKind.INFO and tab.controller.stack.count() == pasos + 1
    assert tab.controller.icon_kind is IconKind.INFO                   # los siguientes de la herramienta Icono tambien
    assert p._icon_color.hex_color().upper() == style.ICON_COLORS["info"].upper()   # el color de fabrica sigue al icono
    p._icon_kind.setCurrentIndex(p._icon_kind.findData("cross"))
    assert tab.controller.icon_kind is IconKind.INFO                   # la cruz tiene su boton: no se vuelve el "otro"
    tab.controller.undo()
    assert tab.controller.selected_item().kind is IconKind.INFO


def test_el_color_propio_el_simbolo_y_el_tamano_se_editan_desde_el_panel(tab):
    _select_new(tab)
    p = tab.panel
    p._icon_color._on_picked("#112233")
    p._icon_glyph_color._on_picked("#EEEEEE")
    p._icon_size.setValue(33.0)
    item = tab.controller.selected_item()
    assert (item.color, item.glyph_color, item.size) == ("#112233", "#EEEEEE", 33.0)
    tab.controller.edit_selected(_merge=False, color=None)
    assert p._icon_color.hex_color().upper() == style.ICON_COLORS["check"].upper()


def test_la_estrella_no_muestra_el_color_del_simbolo(tab):
    _select_new(tab)
    p = tab.panel
    assert p._icon_form.isRowVisible(p._icon_glyph_color)
    p._icon_kind.setCurrentIndex(p._icon_kind.findData("star"))
    QApplication.processEvents()
    assert not p._icon_form.isRowVisible(p._icon_glyph_color)


def test_borde_blanco_y_resplandor_con_sus_controles(tab):
    _select_new(tab)
    p = tab.panel
    assert not p._icon_form.isRowVisible(p._icon_glow_color) and not any(p._icon_form.isRowVisible(r) for r in p._icon_glow_rows)
    p._icon_ring.setChecked(False)
    assert tab.controller.selected_item().ring is False
    p._icon_glow.setChecked(True)
    QApplication.processEvents()
    assert p._icon_form.isRowVisible(p._icon_glow_color) and all(p._icon_form.isRowVisible(r) for r in p._icon_glow_rows)
    p._icon_glow_spins[0].setValue(150)
    p._icon_glow_spins[1].setValue(200)
    item = tab.controller.selected_item()
    assert (item.glow, item.glow_strength, item.glow_size) == (True, 1.5, 2.0)


# --- estilo heredado -------------------------------------------------------------------------------------

def test_el_estilo_elegido_se_hereda_a_los_iconos_nuevos_de_cualquier_boton(tab):
    _select_new(tab)
    p = tab.panel
    p._icon_style.setCurrentIndex(p._icon_style.findData("outline"))
    assert tab.controller.selected_item().style is IconStyle.OUTLINE and tab.controller.icon_style is IconStyle.OUTLINE
    tab.tool_buttons[Tool.CROSS].click()
    _click(tab.canvas, (400.0, 300.0))
    tab.tool_buttons[Tool.CHECK].click()
    _click(tab.canvas, (500.0, 300.0))
    assert [i.style for i in _icons(tab)] == [IconStyle.OUTLINE] * 3


def test_el_boton_de_icono_cambia_su_miniatura_al_cambiar_el_icono_por_defecto(tab):
    antes = tab.tool_buttons[Tool.ICON].icon().cacheKey()
    tab.controller.set_icon_defaults(kind=IconKind.QUESTION)
    assert tab.tool_buttons[Tool.ICON].icon().cacheKey() != antes


# --- proyecto --------------------------------------------------------------------------------------------

def test_los_iconos_colocados_sobreviven_a_guardar_y_reabrir(tab, tmp_path):
    for tool, pt in ((Tool.CHECK, (100.0, 100.0)), (Tool.CROSS, (200.0, 100.0))):
        tab.tool_buttons[tool].click()
        _click(tab.canvas, pt)
    saved = save_doc(tab.doc, tmp_path / "p.anotar.json")
    assert load_doc(saved).items == tab.doc.items
