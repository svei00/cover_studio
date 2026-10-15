"""Lienzo en blanco (fase 3 de Pegar encima): nucleo, dialogo y pestana."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import io
from datetime import datetime

import pytest
from PIL import Image

from core.annotate import blank
from core.annotate.errors import AnnotateError
from core.annotate.model import ImageOverlay
from core.annotate.svg import render_bytes

NOW = datetime(2026, 10, 25, 14, 30, 5)


# --- nucleo ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(1920, 1080), (64, 64), (8000, 4500), [800, 600]])
def test_tamanos_validos(size):
    assert blank.validate_size(size) == tuple(size)


@pytest.mark.parametrize("size", [
    (63, 500), (500, 63), (8001, 500), (500, 8001), (0, 0), (-5, 500), (6000, 6001), (8000, 8000),
    (100.5, 500), ("100", 500), (True, 500), (500,), (500, 500, 3), "800x600", None, 800,
])
def test_tamanos_invalidos(size):
    with pytest.raises(AnnotateError):
        blank.validate_size(size)


def test_el_tope_de_megapixeles_se_explica():
    with pytest.raises(AnnotateError, match="MP"):
        blank.validate_size((7000, 6000))


def test_crear_el_png_liso_con_el_color_y_el_tamano(tmp_path):
    path = blank.create_blank((300, 200), "#336699", tmp_path / "sub" / "carpeta", NOW)
    assert path.parent == tmp_path / "sub" / "carpeta" and path.name == "lienzo-20261025-143005.png"
    img = Image.open(path)
    assert img.size == (300, 200) and img.mode == "RGB" and img.getextrema() == ((51, 51), (102, 102), (153, 153))


def test_dos_lienzos_en_el_mismo_segundo_no_se_pisan(tmp_path):
    a = blank.create_blank((100, 100), "#FFFFFF", tmp_path, NOW)
    b = blank.create_blank((100, 100), "#000000", tmp_path, NOW)
    c = blank.create_blank((100, 100), "#FF0000", tmp_path, NOW)
    assert len({a, b, c}) == 3 and b.name.endswith("-2.png") and c.name.endswith("-3.png")
    assert Image.open(a).getpixel((0, 0)) == (255, 255, 255) and Image.open(b).getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.parametrize("color", ["rojo", "#12345", "#GGGGGG", "123456", "", None, 5])
def test_color_invalido(tmp_path, color):
    with pytest.raises(AnnotateError, match="Color"):
        blank.create_blank((100, 100), color, tmp_path)
    assert not list(tmp_path.iterdir())                                  # no dejo nada


def test_tamano_invalido_no_deja_archivos(tmp_path):
    with pytest.raises(AnnotateError):
        blank.create_blank((10, 10), "#FFFFFF", tmp_path)
    assert not list(tmp_path.iterdir())


def test_no_queda_ningun_temporal(tmp_path):
    blank.create_blank((100, 100), "#FFFFFF", tmp_path)
    assert [p.suffix for p in tmp_path.iterdir()] == [".png"]


def test_no_poder_crear_la_carpeta_es_un_error_claro(tmp_path):
    blocker = tmp_path / "archivo"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(AnnotateError, match="No se pudo crear"):
        blank.create_blank((100, 100), "#FFFFFF", blocker / "dentro")


def test_los_preajustes_son_validos():
    assert blank.PRESETS and all(blank.validate_size(size) == size for _label, size in blank.PRESETS)


def test_nombre_unico_para_otros_prefijos(tmp_path):
    (tmp_path / "pegada-20261025-143005.png").write_bytes(b"x")
    assert blank.unique_png_path(tmp_path, "pegada", NOW).name == "pegada-20261025-143005-2.png"
    assert blank.unique_png_path(tmp_path, "otra", NOW).name == "otra-20261025-143005.png"


# --- dialogo y pestana (Qt) -------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.annotate import tab as tab_module
from ui.annotate.blank_dialog import BlankCanvasDialog
from ui.annotate.tab import AnnotateTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(tab_module, "captures_dir", lambda: tmp_path / "capturas")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    return t


def test_el_dialogo_arranca_con_el_primer_preajuste_y_fondo_blanco(qapp):
    d = BlankCanvasDialog()
    assert d.size_px() == (1920, 1080) and d.color() == "#FFFFFF"
    assert "2.1 MP" in d._hint.text() and d._ok.isEnabled()


def test_elegir_un_preajuste_llena_ancho_y_alto(qapp):
    d = BlankCanvasDialog()
    d._preset.setCurrentIndex(d._preset.findText("Cuadrado 1080 x 1080"))
    assert d.size_px() == (1080, 1080)


def test_tocar_el_ancho_pasa_a_personalizado_y_conserva_lo_escrito(qapp):
    d = BlankCanvasDialog()
    d._width.setValue(1000)
    assert d._preset.currentText() == "Personalizado" and d.size_px() == (1000, 1080)
    d._preset.setCurrentIndex(d._preset.findText("HD 1280 x 720 (16:9)"))
    assert d.size_px() == (1280, 720)


def test_volver_a_escribir_las_medidas_de_un_preajuste_no_cambia_nada_raro(qapp):
    d = BlankCanvasDialog()
    d._width.setValue(1000)
    d._width.setValue(1920)
    assert d.size_px() == (1920, 1080)


def test_el_preajuste_del_portapapeles_solo_aparece_si_hay_imagen(qapp):
    plain = BlankCanvasDialog()
    assert "portapapeles" not in " ".join(plain._preset.itemText(i) for i in range(plain._preset.count()))
    d = BlankCanvasDialog((640, 360))
    assert d._preset.currentText().startswith("Como la imagen del portapapeles (640 x 360)") and d.size_px() == (640, 360)


def test_demasiados_megapixeles_deshabilita_crear_y_lo_explica(qapp):
    d = BlankCanvasDialog()
    d._width.setValue(8000)
    d._height.setValue(8000)
    assert not d._ok.isEnabled() and "MP" in d._hint.text()
    d._height.setValue(1000)
    assert d._ok.isEnabled()


def test_el_color_elegido_sale_en_mayusculas(qapp):
    d = BlankCanvasDialog()
    d._color.set_hex_color("#1a2b3c")
    assert d.color() == "#1A2B3C"


def test_el_boton_esta_activo_sin_captura_abierta(tab):
    assert tab.blank_btn.isEnabled() and tab.doc is None


def test_crear_un_lienzo_lo_abre_como_captura_nueva(tab, tmp_path):
    msgs = []
    tab.statusMessage.connect(msgs.append)
    assert tab.create_blank_canvas((640, 400), "#223344") is True
    assert tab.doc is not None and tab.doc.image_size == (640, 400) and not tab.doc.items
    assert tab.doc.image_path.parent == tmp_path / "capturas" and tab.doc.image_path.name.startswith("lienzo-")
    assert Image.open(tab.doc.image_path).getpixel((5, 5)) == (0x22, 0x33, 0x44)
    assert "640 x 400" in msgs[-1] and "CTRL + MAYUS + V" in msgs[-1]
    assert tab._base_qimage.pixelColor(5, 5).name() == "#223344"


def test_el_boton_pregunta_y_crea(tab, monkeypatch):
    monkeypatch.setattr(AnnotateTab, "_ask_blank_canvas", lambda self: ((300, 200), "#FFFFFF"))
    tab.blank_btn.click()
    assert tab.doc is not None and tab.doc.image_size == (300, 200)


def test_cancelar_el_dialogo_no_crea_nada(tab, tmp_path):
    tab.blank_btn.click()                                              # conftest lo cancela por defecto
    assert tab.doc is None and not (tmp_path / "capturas").exists()


def test_un_tamano_invalido_avisa_y_no_crea(tab, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[1]))
    assert tab.create_blank_canvas((10, 10), "#FFFFFF") is False
    assert shown == ["No se pudo crear el lienzo"] and tab.doc is None


def test_si_se_cancela_por_cambios_sin_guardar_no_queda_un_lienzo_huerfano(tab, tmp_path, monkeypatch):
    tab.create_blank_canvas((300, 200), "#FFFFFF")
    first = tab.doc.image_path
    monkeypatch.setattr(tab, "is_dirty", lambda: True)                  # como si hubiera anotaciones sin guardar
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "cancel")
    assert tab.create_blank_canvas((400, 300), "#000000") is False
    assert tab.doc.image_path == first and tab.doc.image_size == (300, 200)
    assert [p.name for p in (tmp_path / "capturas").iterdir()] == [first.name]      # el segundo se borro


def test_dos_lienzos_seguidos_son_archivos_distintos(tab, tmp_path):
    tab.create_blank_canvas((200, 200), "#FFFFFF")
    a = tab.doc.image_path
    tab.create_blank_canvas((200, 200), "#000000")
    b = tab.doc.image_path
    assert a != b and a.exists() and b.exists()


def test_el_tamano_del_portapapeles_se_lee_solo_si_hay_imagen(tab):
    QGuiApplication.clipboard().clear()
    assert tab._clipboard_image_size() is None
    image = QImage(120, 80, QImage.Format_RGB32)
    image.fill(QColor("#336699"))
    QGuiApplication.clipboard().setImage(image)
    assert tab._clipboard_image_size() == (120, 80)


# --- el flujo completo: lienzo + imagenes pegadas + exportar ----------------------------------


def _clip(width, height, color):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    QGuiApplication.clipboard().setImage(image)


def test_lienzo_con_imagenes_pegadas_se_exporta_completo(tab):
    tab.create_blank_canvas((800, 500), "#F0F0F0")
    _clip(200, 120, "#dc1e1e")
    tab.paste_overlay()
    a = tab.controller.selected_item()
    tab.controller.nudge(-200, -100)
    _clip(160, 100, "#1e1edc")
    tab.paste_overlay()
    b = tab.controller.selected_item()
    tab.controller.nudge(250, 100)
    items = [i for i in tab.doc.items if isinstance(i, ImageOverlay)]
    assert len(items) == 2 and items[0].path != items[1].path
    out = Image.open(io.BytesIO(render_bytes(tab.doc))).convert("RGB")
    ra, rb = tab.controller.item_by_id(a.id).rect, tab.controller.item_by_id(b.id).rect
    assert out.getpixel((int(ra.center[0]), int(ra.center[1]))) == (220, 30, 30)
    assert out.getpixel((int(rb.center[0]), int(rb.center[1]))) == (30, 30, 220)
    assert out.getpixel((5, 5)) == (240, 240, 240) and out.size == (800, 500)


def test_el_tamano_del_portapapeles_encaja_justo_con_la_imagen_pegada(tab, monkeypatch):
    _clip(640, 360, "#dc1e1e")
    monkeypatch.setattr(AnnotateTab, "_ask_blank_canvas", lambda self: (tab._clipboard_image_size(), "#FFFFFF"))
    tab.blank_btn.click()
    tab.paste_overlay()
    (ov,) = [i for i in tab.doc.items if isinstance(i, ImageOverlay)]
    assert (ov.rect.x, ov.rect.y, ov.rect.w, ov.rect.h) == (0, 0, 640, 360)


def test_un_tamano_del_portapapeles_fuera_de_rango_no_se_ofrece(qapp):
    d = BlankCanvasDialog((9000, 5000))
    assert all("portapapeles" not in d._preset.itemText(i) for i in range(d._preset.count())) and d.size_px() == (1920, 1080)
    tiny = BlankCanvasDialog((10, 10))
    assert tiny.size_px() == (1920, 1080)
