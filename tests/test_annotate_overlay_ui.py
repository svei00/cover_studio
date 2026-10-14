"""Pegar encima (Ctrl+Shift+V): pestana, controlador, panel y vista previa."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QUrl, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import QApplication

from core.annotate import overlay as overlay_geometry
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.model import ImageOverlay, Magnifier, Marker, Rect, Redaction
from core.annotate.svg import render_bytes
from ui.annotate import tab as tab_module
from ui.annotate.controller import Tool
from ui.annotate.panel import _PAGE_IMAGE
from ui.annotate.tab import AnnotateTab

RED = "#dc1e1e"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(tab_module, "captures_dir", lambda: tmp_path / "capturas")
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _clip(width=120, height=80, color=RED):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(color))
    QGuiApplication.clipboard().setImage(image)


def _messages(tab):
    got = []
    tab.statusMessage.connect(got.append)
    return got


def _overlays(tab):
    return [i for i in tab.doc.items if isinstance(i, ImageOverlay)]


def _mouse(canvas, kind, pt, buttons=Qt.LeftButton, button=Qt.LeftButton, mods=Qt.NoModifier):
    pos = canvas.image_to_view(pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, mods))


def drag(canvas, a, b, mods=Qt.NoModifier):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, Qt.LeftButton, Qt.NoButton, mods)
    _mouse(canvas, QEvent.MouseButtonRelease, b, Qt.NoButton, Qt.LeftButton, mods)


# --- pegar encima -----------------------------------------------------------------


def test_pegar_encima_agrega_una_imagen_a_tamano_real_y_no_reemplaza_la_captura(tab, tmp_path):
    original = tab.doc.image_path
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    assert tab.doc.image_path == original and tab.doc.image_size == (800, 500)
    assert ov.size == (120, 80) and (ov.rect.w, ov.rect.h) == (120, 80) and ov.rect.center == (400, 250)
    assert ov.path.startswith(str(tmp_path / "capturas")) and os.path.exists(ov.path)
    assert tab.controller.selected_id == ov.id and tab.controller.tool is Tool.SELECT
    assert tab.controller.stack.count() == 1


def test_es_un_solo_paso_de_deshacer(tab):
    _clip()
    tab.paste_overlay()
    tab.controller.undo()
    assert not _overlays(tab)
    tab.controller.redo()
    assert len(_overlays(tab)) == 1


def test_dos_pegados_seguidos_no_se_pisan_el_archivo(tab):
    _clip(120, 80, "#dc1e1e")
    tab.paste_overlay()
    _clip(100, 60, "#1e1edc")
    tab.paste_overlay()
    a, b = _overlays(tab)
    assert a.path != b.path and os.path.exists(a.path) and os.path.exists(b.path)
    assert Image.open(a.path).size == (120, 80) and Image.open(b.path).size == (100, 60)


def test_ctrl_v_sigue_reemplazando_la_captura(tab, tmp_path):
    _clip(64, 48)
    tab.paste_capture()
    assert tab.doc.image_size == (64, 48) and not _overlays(tab)


def test_una_imagen_grande_entra_reducida_y_proporcional(tab):
    _clip(2000, 1000)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    assert ov.size == (2000, 1000) and ov.rect.w <= 0.9 * 800 + 1 and ov.rect.w / ov.rect.h == pytest.approx(2.0, abs=0.01)


def test_pegar_un_archivo_copiado_lo_usa_tal_cual(tab, tmp_path):
    f = tmp_path / "recorte.png"
    Image.new("RGB", (90, 30), (0, 128, 0)).save(f)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f))])
    QGuiApplication.clipboard().setMimeData(mime)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    assert ov.path == str(f) and ov.size == (90, 30)


def test_sin_captura_abierta_avisa_y_no_truena(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(tab_module, "captures_dir", lambda: tmp_path / "capturas")
    t = AnnotateTab()
    msgs = _messages(t)
    _clip()
    t.paste_overlay()
    assert "captura" in msgs[-1].lower() and t.doc is None


def test_sin_imagen_en_el_portapapeles_avisa(tab):
    QGuiApplication.clipboard().clear()
    msgs = _messages(tab)
    tab.paste_overlay()
    assert "No hay una imagen" in msgs[-1] and not _overlays(tab)


def test_el_boton_existe_se_habilita_con_una_captura_y_pega(qapp, tmp_path, tab):
    assert tab.paste_over_btn.isEnabled()
    fresh = AnnotateTab()
    assert not fresh.paste_over_btn.isEnabled()
    _clip()
    tab.paste_over_btn.click()
    assert len(_overlays(tab)) == 1


def test_el_atajo_ctrl_mayus_v_esta_registrado_con_contexto_de_ventana(tab):
    shortcuts = {s.key().toString(): s for s in tab.findChildren(QShortcut)}
    sc = shortcuts[QKeySequence("Ctrl+Shift+V").toString()]
    assert sc.context() == Qt.WindowShortcut
    _clip()
    sc.activated.emit()
    assert len(_overlays(tab)) == 1


# --- vista previa y exportacion -------------------------------------------------------


def test_la_vista_previa_muestra_la_imagen_y_sigue_al_moverla(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    px = lambda x, y: tab._base_qimage.pixelColor(x, y).name()
    assert px(int(ov.rect.x) + 10, int(ov.rect.y) + 10) == RED and px(5, 5) == "#ffffff"
    tab.controller.nudge(50, 0)
    QApplication.processEvents()
    assert px(int(ov.rect.x) + 10, int(ov.rect.y) + 10) == "#ffffff"        # ahi ya no esta
    assert px(int(ov.rect.x) + 70, int(ov.rect.y) + 10) == RED              # y aqui si


def test_pixelar_encima_de_lo_pegado_se_ve_en_la_vista_previa(tab):
    f = tab.doc.image_path.parent / "rayas.png"
    img = Image.new("RGB", (80, 40), (255, 255, 255))
    for x in range(0, 80, 2):
        img.paste((0, 0, 0), (x, 0, x + 1, 40))
    img.save(f)
    tab.controller.add_overlay(f, (80, 40))
    (ov,) = _overlays(tab)
    before = [tab._base_qimage.pixelColor(int(ov.rect.x) + x, int(ov.rect.y) + 10).red() for x in range(20)]
    tab.doc.items.append(Redaction("r9", ov.rect, 20))
    tab.controller.changed.emit()
    QApplication.processEvents()
    after = [tab._base_qimage.pixelColor(int(ov.rect.x) + x, int(ov.rect.y) + 10).red() for x in range(20)]
    assert len(set(before)) == 2 and max(after) - min(after) < 255


def test_la_lupa_de_la_vista_previa_amplia_lo_pegado(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    tab.doc.items.append(Magnifier("l9", Rect(ov.rect.x + 10, ov.rect.y + 10, 20, 20), (700.0, 100.0), 2.0))
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert tab._lens_images()["l9"].pixelColor(5, 5).name() == RED


def test_la_exportacion_incluye_la_imagen_pegada(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    from io import BytesIO
    out = Image.open(BytesIO(render_bytes(tab.doc))).convert("RGB")
    assert out.getpixel((int(ov.rect.x) + 5, int(ov.rect.y) + 5)) == (220, 30, 30)
    assert out.getpixel((5, 5)) == (255, 255, 255)


def test_un_archivo_que_falta_se_avisa_una_sola_vez(tab, tmp_path):
    msgs = _messages(tab)
    tab.doc.items.append(ImageOverlay("g1", str(tmp_path / "borrada.png"), (50, 50), Rect(10, 10, 50, 50)))
    tab.controller.changed.emit()
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert sum("No se encontro la imagen pegada" in m for m in msgs) == 1


# --- mover y redimensionar con el mouse -------------------------------------------------


def test_arrastrar_una_esquina_no_deforma_y_con_mayus_si(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    se = (ov.rect.right, ov.rect.bottom)
    drag(tab.canvas, se, (se[0] + 100, se[1] + 10))
    (a,) = _overlays(tab)
    assert a.rect.w / a.rect.h == pytest.approx(1.5, abs=0.02) and a.rect.w > 200
    drag(tab.canvas, (a.rect.right, a.rect.bottom), (a.rect.right + 60, a.rect.bottom + 5), Qt.ShiftModifier)
    (b,) = _overlays(tab)
    assert abs(b.rect.w / b.rect.h - 1.5) > 0.05                    # con Mayus se estiro libre


def test_mover_arrastrando_desde_dentro(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    c = ov.rect.center
    drag(tab.canvas, c, (c[0] + 40, c[1] + 25))
    (moved,) = _overlays(tab)
    assert (moved.rect.x - ov.rect.x, moved.rect.y - ov.rect.y) == pytest.approx((40, 25), abs=1.5)


def test_una_anotacion_sobre_la_imagen_se_selecciona_primero(tab):
    _clip(200, 120)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    marker = Marker("m9", Rect(ov.rect.x + 20, ov.rect.y + 20, 60, 40))
    tab.doc.items.insert(0, marker)          # creada ANTES que la imagen, pero se ve por encima
    tab.controller.changed.emit()
    tab.controller.select(None)
    _mouse(tab.canvas, QEvent.MouseButtonPress, (marker.rect.x, marker.rect.y + 20))
    _mouse(tab.canvas, QEvent.MouseButtonRelease, (marker.rect.x, marker.rect.y + 20), Qt.NoButton)
    assert tab.controller.selected_id == "m9"


def test_alinear_la_imagen_pegada_al_centro_de_la_captura(tab):
    from core.annotate import align as aligning
    _clip(120, 80)
    tab.paste_overlay()
    tab.controller.nudge(100, 70)
    tab.controller.align_selected(aligning.Align.CENTER_H, to_image=True)
    (ov,) = _overlays(tab)
    assert ov.rect.center[0] == pytest.approx(400, abs=1)


def test_borrar_la_imagen_pegada(tab):
    _clip()
    tab.paste_overlay()
    tab.controller.delete_selected()
    assert not _overlays(tab)
    tab.controller.undo()
    assert len(_overlays(tab)) == 1


# --- panel -------------------------------------------------------------------------------


def test_el_panel_muestra_la_pagina_de_la_imagen_con_su_tamano(tab):
    _clip(120, 80)
    tab.paste_overlay()
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_IMAGE
    assert p._pages.currentWidget().isAncestorOf(p._img_info)          # y la pagina que se ve ES la de la imagen
    assert "100 %" in p._img_info.text() and "120 x 80" in p._img_info.text()
    assert not p._img_real.isEnabled()                                  # ya esta a tamano real


def test_cambiar_opacidad_esquinas_borde_y_sombra_desde_el_panel(tab):
    _clip()
    tab.paste_overlay()
    p = tab.panel
    assert not p._img_form.isRowVisible(p._img_strength_row)
    p._img_opacity.setValue(60)
    p._img_corner.setValue(12.0)
    p._img_border.setChecked(True)
    p._img_shadow.setChecked(True)
    QApplication.processEvents()
    (ov,) = _overlays(tab)
    assert (ov.opacity, ov.corner, ov.border, ov.shadow) == (0.6, 12.0, True, True)
    assert p._img_form.isRowVisible(p._img_strength_row)
    p._img_shadow_strength.setValue(150)
    assert _overlays(tab)[0].shadow_strength == 1.5


def test_tamano_real_vuelve_a_1_a_1_en_un_paso_y_se_puede_deshacer(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    drag(tab.canvas, (ov.rect.right, ov.rect.bottom), (ov.rect.right + 120, ov.rect.bottom + 80))
    big = _overlays(tab)[0]
    assert big.rect.w > 200 and tab.panel._img_real.isEnabled() and "Ampliada" in tab.panel._img_info.text()
    steps = tab.controller.stack.count()
    tab.panel._img_real.click()
    real = _overlays(tab)[0]
    assert (real.rect.w, real.rect.h) == (120, 80) and real.rect.center == pytest.approx(big.rect.center, abs=1)
    assert tab.controller.stack.count() == steps + 1
    tab.controller.undo()
    assert _overlays(tab)[0].rect == big.rect


def test_restablecer_la_opacidad_del_panel(tab):
    _clip()
    tab.paste_overlay()
    tab.controller.edit_selected(_merge=False, opacity=0.5)
    tab.controller.edit_selected(_merge=False, opacity=1.0)
    assert _overlays(tab)[0].opacity == 1.0


# --- proyecto ----------------------------------------------------------------------------


def test_el_proyecto_guarda_y_recupera_la_imagen_pegada(tab, tmp_path):
    _clip(120, 80)
    tab.paste_overlay()
    tab.controller.edit_selected(_merge=False, shadow=True, corner=10.0)
    save_doc(tab.doc)
    loaded = load_doc(sidecar_path(tab.doc.image_path))
    (a,) = [i for i in loaded.items if isinstance(i, ImageOverlay)]
    (b,) = _overlays(tab)
    assert a == b and a.shadow and a.corner == 10.0
    tab.load_capture(tab.doc.image_path)
    QApplication.processEvents()
    assert len(_overlays(tab)) == 1 and tab._base_qimage.pixelColor(int(a.rect.x) + 10, int(a.rect.y) + 10).name() == RED


def test_el_geometro_y_la_pestana_coinciden_en_el_rect_inicial(tab):
    _clip(120, 80)
    tab.paste_overlay()
    (ov,) = _overlays(tab)
    assert ov.rect == overlay_geometry.initial_rect((120, 80), tab.doc.view)


def test_cada_indice_de_pagina_del_panel_apunta_a_su_pagina(tab):
    """Registrar una pagina fuera de orden desplaza las demas: la pagina visible debe ser la de cada tipo de anotacion."""
    from ui.annotate import panel as panel_module
    p = tab.panel
    pages = {
        panel_module._PAGE_IMAGE: p._img_info, panel_module._PAGE_FOCUS: p._focus_dim,
        panel_module._PAGE_STROKE: p._pen_mode, panel_module._PAGE_REDACTION: p._redaction_block,
    }
    for index, widget in pages.items():
        assert p._pages.widget(index).isAncestorOf(widget), index
    assert p._pages.count() == panel_module._PAGE_IMAGE + 1
