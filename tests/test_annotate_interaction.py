import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.annotate import style
from core.annotate.model import ArrowSide, Marker, Redaction, StepBadge, TextLabel
from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _gradient(path: Path, size=(800, 500)) -> Path:
    img = Image.new("RGB", size)
    img.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256) for y in range(size[1]) for x in range(size[0])])
    img.save(path)
    return path


@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(_gradient(tmp_path / "cap.png"))
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    event = QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier)
    QApplication.sendEvent(canvas, event)


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)


def click(canvas, p):
    drag(canvas, p, p)


def test_herramientas_deshabilitadas_hasta_abrir_una_captura(qapp):
    t = AnnotateTab()
    assert not any(b.isEnabled() for b in t.tool_buttons.values())
    assert not t.undo_btn.isEnabled() and not t.delete_btn.isEnabled()


def test_dibujar_un_marcador_con_el_mouse(tab):
    assert all(b.isEnabled() for b in tab.tool_buttons.values())
    tab.tool_buttons[Tool.MARKER].click()
    assert tab.controller.tool is Tool.MARKER
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    item = tab.doc.items[0]
    assert isinstance(item, Marker)
    assert (item.rect.x, item.rect.y) == pytest.approx((100, 100), abs=1)
    assert (item.rect.w, item.rect.h) == pytest.approx((200, 80), abs=1)
    assert tab.tool_buttons[Tool.SELECT].isChecked()
    assert tab.undo_btn.isEnabled() and tab.delete_btn.isEnabled()
    assert "1 anotaciones" in tab.info_label.text()
    assert tab.panel._pages.currentIndex() == 1 and tab.panel._title.text() == "Marcador"


def test_boton_deshacer_y_rehacer(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    tab.undo_btn.click()
    assert tab.doc.items == [] and not tab.undo_btn.isEnabled() and tab.redo_btn.isEnabled()
    assert tab.panel._pages.currentIndex() == 0
    tab.redo_btn.click()
    assert len(tab.doc.items) == 1


def test_mover_con_el_mouse_agarrando_el_borde(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    x0 = tab.doc.items[0].rect.x
    drag(tab.canvas, (100.0, 140.0), (160.0, 160.0))
    assert tab.doc.items[0].rect.x == pytest.approx(x0 + 60, abs=1)


def test_redimensionar_con_un_asa(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    r = tab.doc.items[0].rect
    drag(tab.canvas, (r.right, r.bottom), (r.right + 50, r.bottom + 30))
    assert tab.doc.items[0].rect.w == pytest.approx(r.w + 50, abs=1)
    assert tab.doc.items[0].rect.h == pytest.approx(r.h + 30, abs=1)


def test_texto_se_edita_desde_el_panel_y_se_deshace_de_un_golpe(tab):
    tab.tool_buttons[Tool.TEXT].click()
    click(tab.canvas, (200.0, 200.0))
    assert isinstance(tab.doc.items[0], TextLabel) and tab.panel._text_edit.toPlainText() == "Texto"
    tab.panel._text_edit.setPlainText("Aqui falla")
    assert tab.doc.items[0].text == "Aqui falla"
    tab.panel._text_edit.setPlainText("Aqui falla el IVA")
    tab.undo_btn.click()  # fusionados: un solo paso
    assert tab.doc.items[0].text == "Texto"


def test_preset_de_texto_desde_el_panel(tab):
    tab.tool_buttons[Tool.TEXT].click()
    click(tab.canvas, (200.0, 200.0))
    combo = tab.panel._text_preset
    combo.activated.emit(combo.findData("alerta"))
    item = tab.doc.items[0]
    assert item.border == style.RED and item.border_width == 3.0
    combo.activated.emit(combo.findData("libre"))
    item = tab.doc.items[0]
    assert item.bg is None and item.outline == style.PAGE_BG and item.border_width == 2.5


def test_flecha_del_marcador_desde_el_panel(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    combo = tab.panel._marker_arrow
    combo.setCurrentIndex(combo.findData(ArrowSide.RIGHT.value))
    assert tab.doc.items[0].arrow is ArrowSide.RIGHT
    tab.panel._marker_glow.setChecked(False)
    assert tab.doc.items[0].glow is False


def test_pasos_numerados_y_cambio_de_numero_desde_el_panel(tab):
    for x in (100.0, 200.0):
        tab.tool_buttons[Tool.STEP].click()
        click(tab.canvas, (x, 100.0))
    assert [i.number for i in tab.doc.items] == [1, 2]
    tab.panel._step_number.setValue(7)
    assert tab.doc.items[1].number == 7 and isinstance(tab.doc.items[1], StepBadge)


def test_pixelar_actualiza_el_bitmap_mostrado(tab):
    original = tab.base_image.getpixel((52, 52))[:3]
    tab.tool_buttons[Tool.REDACT].click()
    drag(tab.canvas, (50.0, 50.0), (150.0, 110.0))
    colors = {tab._base_qimage.pixelColor(x, y).rgb() for x in range(50, 55) for y in range(50, 55)}
    assert len(colors) == 1  # dentro de un bloque todo es del mismo color
    assert tab._base_qimage.pixelColor(52, 52).getRgb()[:3] != original
    tab.panel._redaction_block.setValue(40)
    assert tab.doc.items[0].block == 40


def test_suprimir_borra_y_flechas_empujan(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    x0 = tab.doc.items[0].rect.x
    QTest.keyClick(tab.canvas, Qt.Key_Right)
    assert tab.doc.items[0].rect.x == x0 + 1
    QTest.keyClick(tab.canvas, Qt.Key_Right, Qt.ShiftModifier)
    assert tab.doc.items[0].rect.x == x0 + 11
    QTest.keyClick(tab.canvas, Qt.Key_Delete)
    assert tab.doc.items == []
    tab.undo_btn.click()
    assert len(tab.doc.items) == 1


def test_escape_cancela_la_herramienta(tab):
    tab.tool_buttons[Tool.ARROW].click()
    QTest.keyClick(tab.canvas, Qt.Key_Escape)
    assert tab.controller.tool is Tool.SELECT and tab.tool_buttons[Tool.SELECT].isChecked()


def test_boton_borrar(tab):
    tab.tool_buttons[Tool.STEP].click()
    click(tab.canvas, (100.0, 100.0))
    assert tab.delete_btn.isEnabled()
    tab.delete_btn.click()
    assert tab.doc.items == [] and not tab.delete_btn.isEnabled()


def test_abrir_otra_captura_reinicia_el_historial(tab, tmp_path):
    tab.tool_buttons[Tool.STEP].click()
    click(tab.canvas, (100.0, 100.0))
    tab.load_capture(_gradient(tmp_path / "otra.png", (400, 300)))
    assert tab.doc.items == [] and not tab.undo_btn.isEnabled()
    assert tab.doc.image_size == (400, 300)


def test_lo_dibujado_se_exporta(tab, tmp_path):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    out = tmp_path / "salida.png"
    assert tab.export_to(out)
    img = Image.open(out).convert("RGB")
    r = tab.doc.items[0].rect
    px = img.getpixel((round(r.x), round(r.y + r.h / 2)))  # el trazo rojo, centrado en el borde izquierdo
    assert abs(px[0] - 0x62) < 40 and abs(px[1] - 0x11) < 40
    # el proyecto quedo guardado y se puede reabrir
    tab.load_capture(tmp_path / "cap.png")
    assert len(tab.doc.items) == 1


def test_el_lienzo_pinta_asas_de_la_seleccion(tab):
    tab.tool_buttons[Tool.MARKER].click()
    drag(tab.canvas, (100.0, 100.0), (300.0, 180.0))
    img = tab.canvas.grab().toImage()
    corner = tab.canvas.image_to_view((100.0, 100.0))
    # un pixel del asa NO es el color de la captura: es blanco
    assert img.pixelColor(int(corner.x()), int(corner.y())).red() > 240
