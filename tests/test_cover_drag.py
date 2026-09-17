import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest

from core.geometry import CanvasSize, CoverConfig, SubtitlePosition, compute_subtitle_layout
from core.presets import config_from_dict, config_to_dict, load_preset, save_preset


def measure(text: str, size: float) -> float:
    return len(text) * size * 0.5


# --- nucleo: posicion propia del subtitulo -----------------------------------------------------

def _rect(**overrides):
    return compute_subtitle_layout(replace(CoverConfig(canvas=CanvasSize(1584, 891)), **overrides), "Mi subtitulo", measure).rect


def test_sin_posicion_propia_sigue_a_la_posicion_elegida():
    assert _rect().x + _rect().width == pytest.approx(1584 - 24)
    assert _rect(subtitle_position=SubtitlePosition.BOTTOM_LEFT).x == pytest.approx(24)


def test_con_posicion_propia_la_franja_va_ahi_con_su_mismo_tamano():
    auto, propia = _rect(), _rect(subtitle_x=300.0, subtitle_y=200.0)
    assert (propia.x, propia.y) == (300.0, 200.0)
    assert (propia.width, propia.height) == (auto.width, auto.height)
    # y manda sobre el combo
    assert _rect(subtitle_x=300.0, subtitle_y=200.0, subtitle_position=SubtitlePosition.BOTTOM_LEFT).x == 300.0


def test_la_posicion_propia_nunca_saca_la_franja_del_lienzo():
    r = _rect(subtitle_x=-500.0, subtitle_y=-500.0)
    assert (r.x, r.y) == (0.0, 0.0)
    r = _rect(subtitle_x=99999.0, subtitle_y=99999.0)
    assert r.x + r.width <= 1584 + 1e-6 and r.y + r.height <= 891 + 1e-6


def test_solo_una_coordenada_no_cuenta():
    assert _rect(subtitle_x=300.0, subtitle_y=None).x == _rect().x


def test_la_posicion_propia_se_guarda_y_se_recupera(tmp_path):
    c = replace(CoverConfig(), subtitle_x=120.5, subtitle_y=640.0)
    assert config_from_dict(config_to_dict(c)) == c
    assert load_preset(save_preset(c, "movido", tmp_path)) == c


def test_un_preset_viejo_no_trae_posicion_propia():
    c = config_from_dict({"band_color": "#ABCDEF"})
    assert c.subtitle_x is None and c.subtitle_y is None


@pytest.mark.parametrize("data", [
    {"subtitle_x": "izquierda", "subtitle_y": 10},
    {"subtitle_x": 10, "subtitle_y": None},
    {"subtitle_x": None, "subtitle_y": 10},
    {"subtitle_x": True, "subtitle_y": 5},
    {"subtitle_x": [1], "subtitle_y": [2]},
])
def test_una_posicion_danada_o_incompleta_se_ignora(data):
    c = config_from_dict(data)
    assert c.subtitle_x is None and c.subtitle_y is None


# --- interfaz ------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def settle(seconds=0.0, until=None, timeout=8.0):
    """Procesa eventos hasta que se cumpla `until` (o pasen `seconds`)."""
    t0 = time.time()
    while time.time() - t0 < (timeout if until else seconds):
        QApplication.processEvents()
        time.sleep(0.01)
        if until and until():
            break
    QApplication.processEvents()


def render_idle(window):
    pv = window.preview_widget
    return not pv._render_in_flight and pv._pending_request is None and not window._preview_timer.isActive()


@pytest.fixture
def window(qapp, tmp_path):
    Image.new("RGB", (1920, 1080), (90, 120, 160)).save(tmp_path / "foto.png")
    w = MainWindow()
    w.resize(1500, 950)
    w.show()
    QApplication.processEvents()
    w._set_photo(tmp_path / "foto.png")
    w.title_edit.setPlainText("Como armar tu CFDI sin errores")
    w.subtitle_edit.setText("Guia rapida para contadores")
    settle(until=lambda: w.preview_widget._band_rect is not None and w.preview_widget._subtitle_rect is not None and render_idle(w))
    return w


def _send(widget, kind, x, y, buttons, button):
    QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, Qt.NoModifier))


def drag(window, rect_widget, dx, dy, steps=5):
    """Arrastra desde el centro de un rect (en px del widget) y espera a que la vista previa se actualice."""
    pv = window.preview_widget
    cx, cy = rect_widget[0] + rect_widget[2] / 2, rect_widget[1] + rect_widget[3] / 2
    _send(pv, QEvent.MouseButtonPress, cx, cy, Qt.LeftButton, Qt.LeftButton)
    for i in range(1, steps + 1):
        _send(pv, QEvent.MouseMove, cx + dx * i / steps, cy + dy * i / steps, Qt.LeftButton, Qt.NoButton)
    _send(pv, QEvent.MouseButtonRelease, cx + dx, cy + dy, Qt.NoButton, Qt.LeftButton)
    settle(until=lambda: render_idle(window))


def test_la_vista_previa_conoce_el_rect_del_subtitulo(window):
    pv = window.preview_widget
    assert pv._subtitle_rect is not None and pv._subtitle_rect == window._build_subtitle_layout().rect
    window.subtitle_edit.setText("")
    window._trigger_preview_render()
    settle(until=lambda: render_idle(window) and pv._subtitle_rect is None)
    assert pv._subtitle_rect is None


def test_el_subtitulo_gana_si_se_solapa_con_la_banda(window):
    pv = window.preview_widget
    # se pone el subtitulo encima de la banda: el clic ahi es del subtitulo (esta dibujado arriba)
    window.config.subtitle_x, window.config.subtitle_y = 200.0, 100.0
    window._trigger_preview_render()
    settle(until=lambda: render_idle(window) and pv._subtitle_rect.y < 200)
    sub = pv._subtitle_rect_widget()
    centro = (sub[0] + sub[2] / 2, sub[1] + sub[3] / 2)
    assert pv._target_at(*centro)[0] == "subtitle"
    banda = pv._band_rect_widget()
    assert pv._target_at(banda[0] + 4, banda[1] + banda[3] - 4)[0] == "band"   # fuera del subtitulo, la banda
    assert pv._target_at(2, 2) is None                                          # fuera de las dos


def test_arrastrar_el_subtitulo_lo_mueve_y_la_vista_previa_lo_sigue(window):
    pv = window.preview_widget
    antes = window._build_subtitle_layout().rect
    drag(window, pv._subtitle_rect_widget(), -300, -250)
    c = window.config
    assert c.subtitle_x is not None and c.subtitle_y is not None
    assert c.subtitle_x < antes.x - 100 and c.subtitle_y < antes.y - 100
    assert (pv._subtitle_rect.x, pv._subtitle_rect.y) == pytest.approx((c.subtitle_x, c.subtitle_y))   # y la imagen lo muestra
    assert (pv._subtitle_rect.width, pv._subtitle_rect.height) == pytest.approx((antes.width, antes.height))
    assert window.subtitle_reset_position_btn.isEnabled()
    assert window.config.band_margin_left == 90 and window.config.band_margin_top == 80   # la banda no se movio


def test_se_puede_arrastrar_varias_veces_seguidas(window):
    pv = window.preview_widget
    posiciones = []
    for _ in range(3):
        drag(window, pv._subtitle_rect_widget(), -80, -60)
        posiciones.append((window.config.subtitle_x, window.config.subtitle_y))
        assert (pv._subtitle_rect.x, pv._subtitle_rect.y) == pytest.approx(posiciones[-1])
    assert posiciones[0] != posiciones[1] != posiciones[2]


def test_el_subtitulo_no_se_sale_del_lienzo_al_arrastrar(window):
    pv = window.preview_widget
    drag(window, pv._subtitle_rect_widget(), 5000, 5000)
    r, canvas = window._build_subtitle_layout().rect, window.config.canvas
    assert r.x + r.width <= canvas.width + 1e-6 and r.y + r.height <= canvas.height + 1e-6
    drag(window, pv._subtitle_rect_widget(), -9000, -9000)
    assert window.config.subtitle_x == 0.0 and window.config.subtitle_y == 0.0


def test_elegir_una_posicion_o_el_boton_devuelven_a_la_automatica(window):
    pv = window.preview_widget
    drag(window, pv._subtitle_rect_widget(), -300, -250)
    assert window.config.subtitle_x is not None
    window.subtitle_position_combo.setCurrentIndex(window.subtitle_position_combo.findData(SubtitlePosition.BOTTOM_LEFT))
    assert window.config.subtitle_x is None and not window.subtitle_reset_position_btn.isEnabled()
    drag(window, pv._subtitle_rect_widget(), 0, -200)
    assert window.config.subtitle_x is not None and window.subtitle_reset_position_btn.isEnabled()
    window.subtitle_reset_position_btn.click()
    assert window.config.subtitle_x is None and window.config.subtitle_y is None
    assert not window.subtitle_reset_position_btn.isEnabled()
    settle(until=lambda: render_idle(window) and pv._subtitle_rect.x == pytest.approx(24 * 1920 / 1584))   # vuelve abajo-izquierda


def test_la_posicion_movida_se_guarda_en_el_preset_y_se_restaura(window, tmp_path):
    pv = window.preview_widget
    drag(window, pv._subtitle_rect_widget(), -300, -250)
    guardado = load_preset(save_preset(window.config, "movido", tmp_path))
    window._on_reset_all_clicked()
    assert window.config.subtitle_x is None and not window.subtitle_reset_position_btn.isEnabled()
    window._apply_config_to_widgets(guardado)
    assert window.config.subtitle_x == guardado.subtitle_x and window.subtitle_reset_position_btn.isEnabled()


def test_arrastrar_sin_subtitulo_no_hace_nada(window):
    window.subtitle_edit.setText("")
    window._trigger_preview_render()
    settle(until=lambda: render_idle(window) and window.preview_widget._subtitle_rect is None)
    window._on_subtitle_dragged(100.0, 100.0)
    assert window.config.subtitle_x is None


def test_exportar_con_el_subtitulo_movido_lo_deja_donde_se_puso(window, tmp_path):
    drag(window, window.preview_widget._subtitle_rect_widget(), -300, -250)
    r = window._build_subtitle_layout().rect
    window.output_edit.setText(str(tmp_path / "movido.png"))
    window._on_generate_clicked()
    img = Image.open(tmp_path / "movido.png").convert("RGB")
    assert img.getpixel((round(r.x + 1), round(r.y + r.height / 2))) == (0x2F, 0x80, 0xD6)     # el borde (2 px), en su nueva posicion
    abajo = window.config.canvas.height - 24 * 1920 / 1584
    assert img.getpixel((round(window.config.canvas.width - 40), round(abajo - 10))) != (0x2F, 0x80, 0xD6)   # y ya no donde estaba


# --- regresion: la banda (el titulo) dejaba de moverse ---------------------------------------------

def test_la_banda_sigue_a_cada_arrastre_y_la_vista_previa_se_actualiza(window):
    """Antes, tras el primer arrastre la configuracion cambiaba pero la vista previa se quedaba congelada
    en la primera posicion (el manejador nunca pedia redibujar), asi que la banda parecia trabada."""
    pv = window.preview_widget
    vistas = []
    for _ in range(3):
        drag(window, pv._band_rect_widget(), 40, 55)
        vistas.append((round(pv._band_rect.x), round(pv._band_rect.y)))
        assert (pv._band_rect.x, pv._band_rect.y) == pytest.approx((window.config.band_margin_left, window.config.band_margin_top))
    assert len(set(vistas)) == 3, vistas   # cada arrastre movio la imagen, no solo el primero


def test_la_banda_sigue_arrastrandose_aunque_haya_subtitulo(window):
    pv = window.preview_widget
    antes = (window.config.band_margin_left, window.config.band_margin_top)
    drag(window, pv._band_rect_widget(), 60, 80)
    assert (window.config.band_margin_left, window.config.band_margin_top) != antes
    assert window.config.subtitle_x is None   # el subtitulo no se movio


def test_al_arrastrar_la_posicion_cae_en_pixeles_enteros(window):
    drag(window, window.preview_widget._subtitle_rect_widget(), -123, -77)
    assert window.config.subtitle_x == round(window.config.subtitle_x)
    assert window.config.subtitle_y == round(window.config.subtitle_y)
