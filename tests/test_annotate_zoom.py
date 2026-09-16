import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

import hashlib
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.annotate.crop import normalize_crop
from core.annotate.model import Marker, Rect
from ui.annotate.canvas import MAX_VIEW_ZOOM
from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _capture(path: Path, size=(3000, 1800)) -> Path:
    img = Image.new("RGB", size, (240, 240, 240))
    img.putpixel((size[0] // 2, size[1] // 2), (255, 0, 0))
    img.save(path)
    return path


@pytest.fixture
def tab(qapp, tmp_path):
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(_capture(tmp_path / "cap.png"))
    QApplication.processEvents()
    return t


def _event(canvas, kind, view_pos, button, buttons):
    QApplication.sendEvent(canvas, QMouseEvent(kind, view_pos, view_pos, button, buttons, Qt.NoModifier))


def mouse_drag(canvas, a, b, button=Qt.LeftButton):
    """Arrastra con el boton dado entre dos posiciones de PANTALLA."""
    _event(canvas, QEvent.MouseButtonPress, a, button, button)
    _event(canvas, QEvent.MouseMove, b, Qt.NoButton, button)
    _event(canvas, QEvent.MouseButtonRelease, b, button, Qt.NoButton)


def image_drag(canvas, a, b):
    mouse_drag(canvas, canvas.image_to_view(a), canvas.image_to_view(b))


def wheel(canvas, view_pos, dy):
    event = QWheelEvent(view_pos, canvas.mapToGlobal(view_pos), QPoint(0, 0), QPoint(0, dy),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(canvas, event)


def at(tab, x, y):
    return QPointF(x, y)


# --- ajustar y escalas -----------------------------------------------------

def test_empieza_ajustada_y_el_zoom_se_ve_en_la_etiqueta(tab):
    c = tab.canvas
    assert c.is_fitted() and 0 < c.zoom_scale() < 1
    assert "ajustado" in tab.zoom_label.text() and tab.zoom_label.text().startswith("Zoom: ")


def test_la_rueda_hace_zoom_hacia_el_cursor_sin_mover_ese_punto(tab):
    c = tab.canvas
    fit = c.zoom_scale()
    wheel(c, QPointF(c.width() / 2, c.height() / 2), 360)   # primero se acerca (ya no esta ajustada)
    assert not c.is_fitted() and c.zoom_scale() > fit
    pos = QPointF(c.width() * 0.7, c.height() * 0.3)
    before = c.view_to_image(pos)
    wheel(c, pos, 120)
    after = c.view_to_image(pos)
    assert after == pytest.approx(before, abs=1e-6)   # el punto bajo el cursor no se movio
    assert "ajustado" not in tab.zoom_label.text()


def test_cerca_del_ajuste_no_queda_un_hueco_vacio_junto_al_borde(tab):
    c = tab.canvas
    wheel(c, QPointF(c.width() - 5, c.height() / 2), 120)   # acercar justo en el borde derecho
    assert not c.is_fitted()
    right = c.image_to_view((3000, 900)).x()
    left = c.image_to_view((0, 900)).x()
    assert right >= c.width() - 12 - 1e-6 and left <= 12 + 1e-6   # el borde nunca se separa mas del margen


def test_la_rueda_hacia_atras_vuelve_al_ajuste_y_no_baja_de_el(tab):
    c = tab.canvas
    fit = c.zoom_scale()
    wheel(c, QPointF(300, 200), 120)
    wheel(c, QPointF(300, 200), -120)
    assert c.is_fitted() and c.zoom_scale() == pytest.approx(fit)
    wheel(c, QPointF(300, 200), -600)
    assert c.zoom_scale() == pytest.approx(fit)


def test_el_zoom_tiene_tope(tab):
    c = tab.canvas
    for _ in range(40):
        wheel(c, QPointF(300, 200), 120)
    assert c.zoom_scale() == pytest.approx(MAX_VIEW_ZOOM)


def test_botones_ajustar_y_cien_por_ciento(tab):
    c = tab.canvas
    wheel(c, QPointF(400, 300), 240)
    tab.fit_btn.click()
    assert c.is_fitted()
    tab.actual_btn.click()
    assert c.zoom_scale() == 1.0 and not c.is_fitted()
    assert tab.zoom_label.text() == "Zoom: 100 %"


def test_cien_por_ciento_conserva_lo_que_se_mira(tab):
    c = tab.canvas
    wheel(c, QPointF(900, 200), 240)
    center = c.view_to_image(QPointF(c.width() / 2, c.height() / 2))
    tab.actual_btn.click()
    assert c.view_to_image(QPointF(c.width() / 2, c.height() / 2)) == pytest.approx(center, abs=1.0)


def test_otra_captura_empieza_ajustada(tab, tmp_path):
    wheel(tab.canvas, QPointF(400, 300), 240)
    assert not tab.canvas.is_fitted()
    tab.load_capture(_capture(tmp_path / "otra.png", (800, 500)))
    assert tab.canvas.is_fitted()


# --- desplazar --------------------------------------------------------------

def test_el_boton_central_desplaza_y_el_contenido_sigue_al_mouse(tab):
    c = tab.canvas
    tab.actual_btn.click()
    start = QPointF(600, 400)
    anchor = c.view_to_image(start)
    mouse_drag(c, start, QPointF(500, 340), Qt.MiddleButton)
    # el punto que estaba bajo el mouse ahora esta donde se solto
    assert c.image_to_view(anchor).x() == pytest.approx(500, abs=1e-6)
    assert c.image_to_view(anchor).y() == pytest.approx(340, abs=1e-6)
    assert tab.doc.items == []   # desplazar no dibuja nada


def test_espacio_mas_arrastrar_desplaza_en_vez_de_dibujar(tab):
    c = tab.canvas
    tab.actual_btn.click()
    tab.tool_buttons[Tool.MARKER].click()
    c.setFocus()
    anchor = c.view_to_image(QPointF(600, 400))
    QTest.keyPress(c, Qt.Key_Space)
    mouse_drag(c, QPointF(600, 400), QPointF(550, 380))
    QTest.keyRelease(c, Qt.Key_Space)
    assert tab.doc.items == []
    assert c.image_to_view(anchor).x() == pytest.approx(550, abs=1e-6)
    # ya sin Espacio, el mismo gesto vuelve a dibujar
    mouse_drag(c, QPointF(600, 400), QPointF(700, 460))
    assert len(tab.doc.items) == 1


def test_no_se_puede_perder_la_imagen_al_desplazar(tab):
    c = tab.canvas
    tab.actual_btn.click()
    for _ in range(30):
        mouse_drag(c, QPointF(300, 300), QPointF(-4000, -4000), Qt.MiddleButton)
    top_left, bottom_right = c.image_to_view((0, 0)), c.image_to_view((3000, 1800))
    assert bottom_right.x() > 0 and bottom_right.y() > 0   # el borde de la imagen sigue a la vista
    for _ in range(30):
        mouse_drag(c, QPointF(300, 300), QPointF(9000, 9000), Qt.MiddleButton)
    assert c.image_to_view((0, 0)).x() < c.width() and c.image_to_view((0, 0)).y() < c.height()


def test_ajustada_no_hay_nada_que_desplazar(tab):
    c = tab.canvas
    a = c.image_to_view((100, 100))
    mouse_drag(c, QPointF(500, 400), QPointF(300, 200), Qt.MiddleButton)
    assert c.image_to_view((100, 100)).x() == pytest.approx(a.x(), abs=1e-6)


# --- las coordenadas siguen bien con zoom ---------------------------------------

def test_la_conversion_de_ida_y_vuelta_con_zoom(tab):
    c = tab.canvas
    wheel(c, QPointF(900, 300), 360)
    for point in [(0, 0), (1500, 900), (2999, 1799), (123.5, 456.25)]:
        assert c.view_to_image(c.image_to_view(point)) == pytest.approx(point, abs=1e-6)


def test_se_dibuja_con_precision_de_pixel_con_mucho_zoom(tab):
    c = tab.canvas
    wheel(c, c.image_to_view((1500, 900)), 120 * 16)   # mucho zoom sobre el pixel rojo
    assert c.zoom_scale() > 4
    tab.tool_buttons[Tool.MARKER_PLAIN].click()
    image_drag(c, (1495, 895), (1505, 905))
    marker = tab.doc.items[0]
    assert isinstance(marker, Marker)
    assert (marker.rect.x, marker.rect.y, marker.rect.w, marker.rect.h) == pytest.approx((1495, 895, 10, 10), abs=0.5)


def test_la_tolerancia_de_clic_se_achica_con_el_zoom(tab):
    c = tab.canvas
    fitted = c._tolerance()
    wheel(c, QPointF(600, 400), 120 * 8)
    assert c._tolerance() < fitted / 3


def test_seleccionar_funciona_con_zoom(tab):
    c = tab.canvas
    tab.controller.doc.items.append(Marker("a1", Rect(1400, 800, 200, 100)))
    tab.controller.changed.emit()
    wheel(c, c.image_to_view((1500, 850)), 120 * 6)
    tab.controller.select(None)
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, c.image_to_view((1400, 850)).toPoint())
    assert tab.controller.selected_id == "a1"


# --- ventana, recorte y exportacion --------------------------------------------

def test_cambiar_el_tamano_de_la_ventana_conserva_lo_que_se_mira(tab):
    c = tab.canvas
    wheel(c, QPointF(900, 300), 480)
    center = c.view_to_image(QPointF(c.width() / 2, c.height() / 2))
    tab.resize(1000, 700)
    QApplication.processEvents()
    assert c.view_to_image(QPointF(c.width() / 2, c.height() / 2)) == pytest.approx(center, abs=1.0)


def test_entrar_y_salir_de_recortar_conserva_el_zoom_y_lo_que_se_mira(tab):
    c = tab.canvas
    wheel(c, QPointF(900, 300), 480)
    scale = c.zoom_scale()
    center = c.view_to_image(QPointF(c.width() / 2, c.height() / 2))
    tab.tool_buttons[Tool.CROP].click()
    assert c.zoom_scale() == pytest.approx(scale)
    assert c.view_to_image(QPointF(c.width() / 2, c.height() / 2)) == pytest.approx(center, abs=1.0)
    tab.controller.set_crop(Rect(500, 300, 1500, 900))
    tab.controller.set_tool(Tool.SELECT)
    assert c.zoom_scale() == pytest.approx(scale)


def test_el_zoom_no_cambia_lo_que_se_exporta(tab, tmp_path):
    tab.doc.items.append(Marker("a1", Rect(1400, 800, 200, 100)))
    tab.controller.changed.emit()

    def digest(name):
        out = tmp_path / name
        assert tab.export_to(out)
        return hashlib.sha256(out.read_bytes()).hexdigest()

    ajustada = digest("a.png")
    wheel(tab.canvas, QPointF(900, 300), 600)
    mouse_drag(tab.canvas, QPointF(500, 400), QPointF(300, 200), Qt.MiddleButton)
    assert digest("b.png") == ajustada


def test_pintar_con_mucho_zoom_no_falla(tab):
    wheel(tab.canvas, QPointF(600, 400), 120 * 14)
    assert not tab.canvas.grab().isNull()
