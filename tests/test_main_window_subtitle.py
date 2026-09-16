import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from dataclasses import replace

from PIL import Image
from PySide6.QtWidgets import QApplication

from core.geometry import CoverConfig, SubtitlePosition
from core.presets import load_preset, save_preset
from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow()
    w.title_edit.setPlainText("Titulo de prueba")
    w.output_edit.setText(str(tmp_path / "salida.png"))
    return w


def _set(slider, value):
    """Mueve el control como lo hace el usuario (set_value no emite senales)."""
    slider._spin.setValue(value)


def test_los_controles_nuevos_arrancan_con_los_valores_pedidos(window):
    c = CoverConfig()
    assert window.subtitle_edit.text() == ""
    assert window.subtitle_text_color_picker.hex_color().upper() == "#F1EBDF"
    assert window.subtitle_bg_color_picker.hex_color().upper() == "#1B3350"
    assert window.subtitle_border_color_picker.hex_color().upper() == "#2F80D6"
    assert window.subtitle_opacity_slider.value() == 90 and window.subtitle_border_slider.value() == 2.0
    assert window.subtitle_font_slider.value() == c.subtitle_font_size
    assert window.subtitle_position_combo.currentData() == SubtitlePosition.BOTTOM_RIGHT
    labels = [window.subtitle_position_combo.itemText(i) for i in range(window.subtitle_position_combo.count())]
    assert labels == ["Abajo-derecha", "Abajo-izquierda", "Abajo-centro"]


def test_los_rangos_son_los_pedidos(window):
    assert (window.subtitle_opacity_slider._spin.minimum(), window.subtitle_opacity_slider._spin.maximum()) == (0, 100)
    assert (window.subtitle_border_slider._spin.minimum(), window.subtitle_border_slider._spin.maximum()) == (0, 12)


def test_cada_control_cambia_la_configuracion(window):
    window.subtitle_position_combo.setCurrentIndex(window.subtitle_position_combo.findData(SubtitlePosition.BOTTOM_CENTER))
    window.subtitle_text_color_picker.set_hex_color("#111111")
    window.subtitle_bg_color_picker.set_hex_color("#222222")
    window.subtitle_border_color_picker.set_hex_color("#333333")
    _set(window.subtitle_opacity_slider, 60)
    _set(window.subtitle_border_slider, 4.0)
    _set(window.subtitle_font_slider, 44)
    c = window.config
    assert c.subtitle_position is SubtitlePosition.BOTTOM_CENTER
    assert (c.subtitle_text_color, c.subtitle_bg_color, c.subtitle_border_color) == ("#111111", "#222222", "#333333")
    assert (c.subtitle_bg_opacity, c.subtitle_border_width, c.subtitle_font_size) == (0.6, 4.0, 44)


def test_sin_texto_no_hay_subtitulo_y_con_texto_si(window):
    assert window._build_subtitle_layout() is None
    window.subtitle_edit.setText("   ")
    assert window._build_subtitle_layout() is None
    window.subtitle_edit.setText("hola Mundo")
    layout = window._build_subtitle_layout()
    assert layout is not None and layout.lines == ("hola Mundo",)   # tal como se escribio


def test_la_vista_previa_se_pide_con_el_subtitulo_y_con_cada_cambio(window):
    pedidos = []
    window.preview_widget.request_render = lambda *a, **k: pedidos.append(a)
    window.subtitle_edit.setText("Mi subtitulo")
    window._trigger_preview_render()
    assert pedidos[-1][4] is not None and pedidos[-1][0].subtitle_bg_opacity == 0.9
    _set(window.subtitle_opacity_slider, 30)
    _set(window.subtitle_border_slider, 8.0)
    window._trigger_preview_render()
    assert pedidos[-1][0].subtitle_bg_opacity == 0.3 and pedidos[-1][0].subtitle_border_width == 8.0
    window.subtitle_edit.setText("")
    window._trigger_preview_render()
    assert pedidos[-1][4] is None


def test_los_controles_nuevos_reprograman_la_vista_previa(window):
    inicio = []
    window._preview_timer.timeout.disconnect()
    window._preview_timer.timeout.connect(lambda: inicio.append(1))
    for accion in (
        lambda: window.subtitle_edit.setText("x"),
        lambda: _set(window.subtitle_opacity_slider, 20),
        lambda: _set(window.subtitle_border_slider, 6.0),
        lambda: _set(window.subtitle_font_slider, 50),
        lambda: window.subtitle_bg_color_picker.set_hex_color("#445566"),
        lambda: window.subtitle_position_combo.setCurrentIndex(1),
    ):
        window._preview_timer.stop()
        accion()
        assert window._preview_timer.isActive()


def test_un_preset_con_subtitulo_llena_los_controles_y_uno_viejo_usa_los_defaults(window, tmp_path):
    c = replace(CoverConfig(), subtitle_bg_opacity=0.4, subtitle_border_width=7.0,
                subtitle_position=SubtitlePosition.BOTTOM_LEFT, subtitle_text_color="#ABCDEF")
    window._apply_config_to_widgets(load_preset(save_preset(c, "p", tmp_path)))
    assert window.subtitle_opacity_slider.value() == 40 and window.subtitle_border_slider.value() == 7.0
    assert window.subtitle_position_combo.currentData() == SubtitlePosition.BOTTOM_LEFT
    assert window.subtitle_text_color_picker.hex_color().upper() == "#ABCDEF"
    (tmp_path / "viejo.json").write_text('{"band_color": "#ABCDEF"}', encoding="utf-8")
    window._apply_config_to_widgets(load_preset(tmp_path / "viejo.json"))
    assert window.subtitle_opacity_slider.value() == 90 and window.subtitle_border_slider.value() == 2.0


def test_restablecer_todo_vuelve_a_los_valores_del_subtitulo(window):
    _set(window.subtitle_opacity_slider, 10)
    window._on_reset_all_clicked()
    assert window.subtitle_opacity_slider.value() == 90 and window.config.subtitle_bg_opacity == 0.9


def _generar(window, tmp_path, nombre):
    out = tmp_path / nombre
    window.output_edit.setText(str(out))
    window._on_generate_clicked()
    assert out.exists()
    return Image.open(out).convert("RGB")


def test_generar_exporta_el_subtitulo_con_la_opacidad_y_el_grosor_elegidos(window, tmp_path):
    window.subtitle_edit.setText("Mi subtitulo")
    _set(window.subtitle_opacity_slider, 60)
    _set(window.subtitle_border_slider, 4.0)
    con = _generar(window, tmp_path, "con-borde.png")
    r = window._build_subtitle_layout().rect
    y = round(r.y + r.height / 2)
    assert con.getpixel((round(r.x + 2), y)) == (0x2F, 0x80, 0xD6)     # borde al 100 %
    relleno = con.getpixel((round(r.x + 10), y))
    esperado = tuple(round(f * 0.6 + b * 0.4) for f, b in zip((0x1B, 0x33, 0x50), (0x6E, 0x6E, 0x6E)))
    assert all(abs(a - b) <= 2 for a, b in zip(relleno, esperado))
    _set(window.subtitle_border_slider, 0.0)
    sin = _generar(window, tmp_path, "sin-borde.png")
    assert sin.getpixel((round(r.x + 2), y)) != (0x2F, 0x80, 0xD6)


def test_sin_subtitulo_el_png_no_lleva_la_franja(window, tmp_path):
    sin = _generar(window, tmp_path, "sin-subtitulo.png")
    window.subtitle_edit.setText("Mi subtitulo")
    con = _generar(window, tmp_path, "con-subtitulo.png")
    r = window._build_subtitle_layout().rect
    punto = (round(r.x + 10), round(r.y + r.height / 2))
    assert sin.getpixel(punto) == (0x6E, 0x6E, 0x6E) and con.getpixel(punto) != (0x6E, 0x6E, 0x6E)
