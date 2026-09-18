import os
import re
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.geometry import (
    CanvasSize,
    CoverConfig,
    GradientDirection,
    build_svg,
    compute_subtitle_layout,
    render_png,
)
from core.presets import config_from_dict, config_to_dict, load_preset, save_preset


def measure(text: str, size: float) -> float:
    return len(text) * size * 0.5


def _svg(**overrides):
    config = replace(CoverConfig(), **overrides)
    return build_svg(config, ["Titulo"], 78.0, None, compute_subtitle_layout(config, "Mi subtitulo", measure))


# --- configuracion --------------------------------------------------------------------------

def test_los_defaults_del_degradado_y_el_contorno():
    c = CoverConfig()
    assert c.subtitle_gradient is False and c.subtitle_bg_color2 == "#3182DF"
    assert c.subtitle_gradient_direction is GradientDirection.HORIZONTAL
    assert c.subtitle_outline_enabled is False and c.subtitle_outline_color == "#B38E5D"   # el del titulo


def test_se_guardan_y_se_recuperan(tmp_path):
    c = replace(CoverConfig(), subtitle_gradient=True, subtitle_bg_color="#21B868", subtitle_bg_color2="#3182DF",
                subtitle_gradient_direction=GradientDirection.DIAGONAL, subtitle_outline_enabled=True,
                subtitle_outline_color="#112233")
    assert config_from_dict(config_to_dict(c)) == c
    assert load_preset(save_preset(c, "degradado", tmp_path)) == c


def test_un_preset_viejo_abre_sin_degradado_ni_contorno():
    c = config_from_dict({"band_color": "#ABCDEF", "subtitle_bg_opacity": 0.5})
    assert (c.subtitle_gradient, c.subtitle_outline_enabled) == (False, False) and c.subtitle_bg_opacity == 0.5


@pytest.mark.parametrize("data,campo,esperado", [
    ({"subtitle_bg_color2": "azul"}, "subtitle_bg_color2", "#3182DF"),
    ({"subtitle_bg_color2": 7}, "subtitle_bg_color2", "#3182DF"),
    ({"subtitle_outline_color": "#12"}, "subtitle_outline_color", "#B38E5D"),
    ({"subtitle_gradient_direction": "espiral"}, "subtitle_gradient_direction", GradientDirection.HORIZONTAL),
    ({"subtitle_gradient": "si"}, "subtitle_gradient", False),
    ({"subtitle_outline_enabled": 1}, "subtitle_outline_enabled", False),
])
def test_un_dato_danado_usa_el_de_siempre(data, campo, esperado):
    assert getattr(config_from_dict(data), campo) == esperado


# --- SVG ---------------------------------------------------------------------------------------

def test_sin_degradado_el_relleno_es_un_color_solido():
    svg = _svg()
    assert "linearGradient" not in svg
    assert re.search(r'<rect[^>]*fill="#1B3350"[^>]*fill-opacity="0.90"', svg)


@pytest.mark.parametrize("direccion,vector", [
    (GradientDirection.HORIZONTAL, ("0", "0", "1", "0")),
    (GradientDirection.VERTICAL, ("0", "0", "0", "1")),
    (GradientDirection.DIAGONAL, ("0", "0", "1", "1")),
])
def test_el_degradado_tiene_dos_colores_y_la_direccion_elegida(direccion, vector):
    svg = _svg(subtitle_gradient=True, subtitle_bg_color="#21B868", subtitle_bg_color2="#3182DF",
               subtitle_gradient_direction=direccion)
    grad = re.search(r'<linearGradient id="subtitleGradient" x1="(\d)" y1="(\d)" x2="(\d)" y2="(\d)">(.*?)</linearGradient>', svg)
    assert grad.groups()[:4] == vector
    assert re.findall(r'stop offset="(\d)" stop-color="(#\w+)"', grad.group(5)) == [("0", "#21B868"), ("1", "#3182DF")]
    rect = re.search(r'<rect[^>]*fill="url\(#subtitleGradient\)"[^>]*/>', svg).group(0)
    assert 'fill-opacity="0.90"' in rect                      # la opacidad del fondo aplica a todo el degradado
    assert svg.count("<linearGradient") == 1 and svg.count('fill="url(#subtitleGradient)"') == 1


def test_el_degradado_no_toca_el_borde_ni_el_texto():
    svg = _svg(subtitle_gradient=True)
    rect = re.search(r'<rect[^>]*subtitleGradient[^>]*/>', svg).group(0)
    assert 'stroke="#2F80D6"' in rect and "stroke-opacity" not in rect
    assert 'fill="#F1EBDF"' in re.search(r'<text[^>]*>Mi subtitulo</text>', svg).group(0)


def test_sin_contorno_el_texto_va_sin_trazo():
    texto = re.search(r'<text[^>]*>Mi subtitulo</text>', _svg()).group(0)
    assert "stroke" not in texto and "paint-order" not in texto


def test_el_contorno_se_dibuja_como_el_del_titulo():
    config = replace(CoverConfig(), subtitle_outline_enabled=True, subtitle_outline_color="#112233", subtitle_font_size=36.0)
    svg = build_svg(config, ["Titulo"], 78.0, None, compute_subtitle_layout(config, "Mi subtitulo", measure))
    texto = re.search(r'<text[^>]*>Mi subtitulo</text>', svg).group(0)
    assert 'stroke="#112233"' in texto and 'paint-order="stroke fill"' in texto and 'fill="#F1EBDF"' in texto
    assert 'stroke-width="2.00"' in texto                              # max(2, 36 * 0.02), la regla del titulo
    grande = replace(config, subtitle_font_size=120.0)
    svg2 = build_svg(grande, ["Titulo"], 78.0, None, compute_subtitle_layout(grande, "Hola", measure))
    assert 'stroke-width="2.40"' in re.search(r'<text[^>]*>Hola</text>', svg2).group(0)   # 120 * 0.02
    # y el titulo no cambia: su contorno sigue siendo el suyo (apagado)
    titulo = re.search(r'<text[^>]*>Titulo</text>', svg).group(0)
    assert "stroke" not in titulo


# --- pixeles: lo que sale en el PNG -------------------------------------------------------------------

RADIO = 0.4 * 48   # esquinas redondeadas de la franja con letra de 48 px: las esquinas NO tienen relleno


def _render(tmp_path, name, **overrides):
    opciones = {"subtitle_font_size": 48.0, "subtitle_border_width": 0.0, "subtitle_bg_opacity": 1.0, **overrides}
    config = replace(CoverConfig(canvas=CanvasSize(1584, 891)), **opciones)
    layout = compute_subtitle_layout(config, "Gradiente de prueba", measure)
    out = tmp_path / name
    render_png(build_svg(config, ["T"], 78.0, None, layout), out, 1584, 891)
    return Image.open(out).convert("RGB"), layout.rect


def _cerca(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _puntos(r):
    """Puntos DENTRO de la franja y sin texto: pasada la esquina redondeada, pegados al borde de arriba o de abajo."""
    return {
        "izq": (round(r.x + RADIO + 2), round(r.y + 3)), "der": (round(r.x + r.width - RADIO - 2), round(r.y + 3)),
        "izq_abajo": (round(r.x + RADIO + 2), round(r.y + r.height - 3)),
        "der_abajo": (round(r.x + r.width - RADIO - 2), round(r.y + r.height - 3)),
    }


def test_horizontal_va_del_primer_color_a_la_izquierda_al_segundo_a_la_derecha(tmp_path):
    img, r = _render(tmp_path, "h.png", subtitle_gradient=True, subtitle_bg_color="#FF0000", subtitle_bg_color2="#0000FF")
    p = _puntos(r)
    izq, der = img.getpixel(p["izq"]), img.getpixel(p["der"])
    assert _cerca(izq, (255, 0, 0), 30) and _cerca(der, (0, 0, 255), 30)
    assert izq[0] > der[0] and der[2] > izq[2]
    medio = img.getpixel((round(r.x + r.width / 2), round(r.y + 3)))
    assert abs(medio[0] - 128) < 25 and abs(medio[2] - 128) < 25           # a la mitad, una mezcla de los dos
    assert _cerca(img.getpixel(p["izq_abajo"]), izq, 6)                      # y no varia de arriba a abajo


def test_vertical_va_de_arriba_a_abajo(tmp_path):
    img, r = _render(tmp_path, "v.png", subtitle_gradient=True, subtitle_bg_color="#FF0000", subtitle_bg_color2="#0000FF",
                     subtitle_gradient_direction=GradientDirection.VERTICAL)
    p = _puntos(r)
    assert _cerca(img.getpixel(p["izq"]), (255, 0, 0), 20)
    assert _cerca(img.getpixel(p["izq_abajo"]), (0, 0, 255), 20)
    assert _cerca(img.getpixel(p["der"]), img.getpixel(p["izq"]), 6)         # no varia a lo ancho


def test_diagonal_une_las_esquinas_opuestas(tmp_path):
    img, r = _render(tmp_path, "d.png", subtitle_gradient=True, subtitle_bg_color="#FF0000", subtitle_bg_color2="#0000FF",
                     subtitle_gradient_direction=GradientDirection.DIAGONAL)
    p = _puntos(r)
    arriba_izq, abajo_der = img.getpixel(p["izq"]), img.getpixel(p["der_abajo"])
    assert arriba_izq[0] > 200 and arriba_izq[2] < 60 and abajo_der[2] > 200 and abajo_der[0] < 60
    otra = img.getpixel(p["der"])                                              # la otra diagonal: una mezcla
    assert 40 < otra[0] < 215 and 40 < otra[2] < 215


def test_la_opacidad_aplica_a_los_dos_colores_del_degradado(tmp_path):
    img, r = _render(tmp_path, "op.png", subtitle_gradient=True, subtitle_bg_color="#FF0000", subtitle_bg_color2="#0000FF",
                     subtitle_bg_opacity=0.5)
    fondo, p = (0x6E, 0x6E, 0x6E), _puntos(r)
    esperado_izq = tuple(round(f * 0.5 + b * 0.5) for f, b in zip((255, 0, 0), fondo))
    esperado_der = tuple(round(f * 0.5 + b * 0.5) for f, b in zip((0, 0, 255), fondo))
    assert _cerca(img.getpixel(p["izq"]), esperado_izq, 18)
    assert _cerca(img.getpixel(p["der"]), esperado_der, 18)


def test_el_contorno_del_texto_aparece_en_el_png_y_sin_el_no(tmp_path):
    con, r = _render(tmp_path, "con.png", subtitle_outline_enabled=True, subtitle_outline_color="#B38E5D")
    sin, _ = _render(tmp_path, "sin.png")
    caja = (round(r.x), round(r.y), round(r.x + r.width), round(r.y + r.height))
    contar = lambda im: dict((c, n) for n, c in im.crop(caja).getcolors(maxcolors=1_000_000)).get(_hex("#B38E5D"), 0)  # noqa: E731
    assert contar(con) > 30 and contar(sin) == 0


# --- ventana: controles y coordenadas ---------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def settle(until, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        QApplication.processEvents()
        time.sleep(0.01)
        if until():
            break
    QApplication.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow()
    w.resize(1500, 950)
    w.show()
    QApplication.processEvents()
    w.title_edit.setPlainText("Titulo de prueba")
    w.subtitle_edit.setText("Mi subtitulo")
    w.output_edit.setText(str(tmp_path / "salida.png"))
    QApplication.processEvents()
    return w


def _set(slider, value):
    slider._spin.setValue(value)


def test_los_controles_nuevos_existen_con_sus_defaults(window):
    assert not window.subtitle_gradient_checkbox.isChecked() and window.subtitle_gradient_panel.isHidden()
    assert window.subtitle_bg_color2_picker.hex_color().upper() == "#3182DF"
    assert not window.subtitle_outline_checkbox.isChecked() and not window.subtitle_outline_color_picker.isEnabled()
    assert window.subtitle_outline_color_picker.hex_color().upper() == "#B38E5D"
    assert window.subtitle_step_spin.value() == 10
    labels = [window.subtitle_gradient_direction_combo.itemText(i) for i in range(window.subtitle_gradient_direction_combo.count())]
    assert labels == ["Horizontal (izq. a der.)", "Vertical (arriba a abajo)", "Diagonal"]


def test_el_degradado_se_enciende_y_muestra_sus_controles(window):
    window.subtitle_gradient_checkbox.setChecked(True)
    assert window.config.subtitle_gradient and not window.subtitle_gradient_panel.isHidden()
    window.subtitle_bg_color2_picker.set_hex_color("#445566")
    window.subtitle_gradient_direction_combo.setCurrentIndex(window.subtitle_gradient_direction_combo.findData(GradientDirection.VERTICAL))
    assert window.config.subtitle_bg_color2 == "#445566" and window.config.subtitle_gradient_direction is GradientDirection.VERTICAL
    window.subtitle_gradient_checkbox.setChecked(False)
    assert window.subtitle_gradient_panel.isHidden() and not window.config.subtitle_gradient


def test_el_boton_de_colores_de_marca_usa_la_banda_y_el_acento(window):
    window.band_color_picker.set_hex_color("#21B868")
    window.accent_color_picker.set_hex_color("#3182DF")
    window.subtitle_brand_btn.click()
    c = window.config
    assert c.subtitle_gradient and c.subtitle_bg_color.upper() == c.band_color.upper() and c.subtitle_bg_color2.upper() == c.accent_color.upper()
    assert window.subtitle_gradient_checkbox.isChecked() and not window.subtitle_gradient_panel.isHidden()


def test_el_contorno_del_texto_se_enciende_y_habilita_su_color(window):
    window.subtitle_outline_checkbox.setChecked(True)
    assert window.config.subtitle_outline_enabled and window.subtitle_outline_color_picker.isEnabled()
    window.subtitle_outline_color_picker.set_hex_color("#112233")
    assert window.config.subtitle_outline_color == "#112233"


def test_los_controles_nuevos_reprograman_la_vista_previa(window):
    for accion in (
        lambda: window.subtitle_gradient_checkbox.setChecked(True),
        lambda: window.subtitle_bg_color2_picker.set_hex_color("#445566"),
        lambda: window.subtitle_gradient_direction_combo.setCurrentIndex(2),
        lambda: window.subtitle_outline_checkbox.setChecked(True),
        lambda: window.subtitle_outline_color_picker.set_hex_color("#102030"),
    ):
        window._preview_timer.stop()
        accion()
        assert window._preview_timer.isActive()


def test_un_preset_llena_los_controles_nuevos(window, tmp_path):
    c = replace(CoverConfig(), subtitle_gradient=True, subtitle_bg_color2="#ABCDEF", subtitle_outline_enabled=True,
                subtitle_gradient_direction=GradientDirection.DIAGONAL, subtitle_x=300.0, subtitle_y=200.0)
    window._apply_config_to_widgets(load_preset(save_preset(c, "p", tmp_path)))
    assert window.subtitle_gradient_checkbox.isChecked() and not window.subtitle_gradient_panel.isHidden()
    assert window.subtitle_bg_color2_picker.hex_color().upper() == "#ABCDEF"
    assert window.subtitle_outline_checkbox.isChecked() and window.subtitle_outline_color_picker.isEnabled()
    assert (window.subtitle_x_spin.value(), window.subtitle_y_spin.value()) == (300, 200)


# --- coordenadas -------------------------------------------------------------------------------------------

def test_x_e_y_muestran_donde_esta_la_franja_y_se_apagan_sin_subtitulo(window):
    r = window._build_subtitle_layout().rect
    assert (window.subtitle_x_spin.value(), window.subtitle_y_spin.value()) == (round(r.x), round(r.y))
    assert window.subtitle_x_spin.isEnabled() and all(b.isEnabled() for b in window.subtitle_nudge_buttons.values())
    assert window.subtitle_x_spin.maximum() == int(window.config.canvas.width - r.width)     # no se sale del lienzo
    assert window.subtitle_y_spin.maximum() == int(window.config.canvas.height - r.height)
    window.subtitle_edit.setText("")
    assert not window.subtitle_x_spin.isEnabled() and not any(b.isEnabled() for b in window.subtitle_nudge_buttons.values())


def test_escribir_x_e_y_coloca_la_franja_ahi(window):
    window.subtitle_x_spin.setValue(480)
    window.subtitle_y_spin.setValue(300)
    assert (window.config.subtitle_x, window.config.subtitle_y) == (480.0, 300.0)
    r = window._build_subtitle_layout().rect
    assert (r.x, r.y) == (480.0, 300.0)
    assert window.subtitle_reset_position_btn.isEnabled()


def test_los_cuatro_botones_mueven_de_a_un_paso(window):
    window.subtitle_x_spin.setValue(500)
    window.subtitle_y_spin.setValue(400)
    pos = lambda: (window.subtitle_x_spin.value(), window.subtitle_y_spin.value())  # noqa: E731
    window.subtitle_nudge_buttons["left"].click()
    assert pos() == (490, 400)
    window.subtitle_nudge_buttons["right"].click()
    window.subtitle_nudge_buttons["right"].click()
    assert pos() == (510, 400)
    window.subtitle_nudge_buttons["up"].click()
    assert pos() == (510, 390)
    window.subtitle_nudge_buttons["down"].click()
    window.subtitle_nudge_buttons["down"].click()
    assert pos() == (510, 410)
    assert (window.config.subtitle_x, window.config.subtitle_y) == (510.0, 410.0)


def test_derecha_y_abajo_hacen_una_diagonal_y_el_paso_es_configurable(window):
    window.subtitle_x_spin.setValue(300)
    window.subtitle_y_spin.setValue(300)
    window.subtitle_step_spin.setValue(25)
    window.subtitle_nudge_buttons["right"].click()
    window.subtitle_nudge_buttons["down"].click()
    assert (window.subtitle_x_spin.value(), window.subtitle_y_spin.value()) == (325, 325)


def test_los_botones_no_sacan_la_franja_del_lienzo(window):
    window.subtitle_x_spin.setValue(0)
    window.subtitle_y_spin.setValue(0)
    window.subtitle_nudge_buttons["left"].click()
    window.subtitle_nudge_buttons["up"].click()
    assert (window.subtitle_x_spin.value(), window.subtitle_y_spin.value()) == (0, 0)
    window.subtitle_step_spin.setValue(500)
    for _ in range(10):
        window.subtitle_nudge_buttons["right"].click()
        window.subtitle_nudge_buttons["down"].click()
    r = window._build_subtitle_layout().rect
    assert r.x + r.width <= window.config.canvas.width + 1e-6 and r.y + r.height <= window.config.canvas.height + 1e-6
    assert window.subtitle_x_spin.value() == window.subtitle_x_spin.maximum()


def test_los_numeros_siguen_a_la_franja_cuando_cambia_el_texto_o_el_tamano(window):
    antes = window.subtitle_x_spin.value()
    window.subtitle_edit.setText("Un subtitulo bastante mas largo que el anterior para que la franja sea ancha")
    assert window.subtitle_x_spin.value() < antes                  # abajo-derecha: una franja mas ancha empieza mas a la izquierda
    r = window._build_subtitle_layout().rect
    assert window.subtitle_x_spin.value() == round(r.x)
    _set(window.subtitle_font_slider, 80)
    r = window._build_subtitle_layout().rect
    assert window.subtitle_y_spin.value() == round(r.y)


def test_elegir_una_posicion_o_volver_a_automatica_actualiza_los_numeros(window):
    window.subtitle_x_spin.setValue(100)
    window.subtitle_y_spin.setValue(100)
    window.subtitle_reset_position_btn.click()
    r = window._build_subtitle_layout().rect
    assert window.config.subtitle_x is None and window.subtitle_x_spin.value() == round(r.x) != 100
    window.subtitle_x_spin.setValue(100)
    window.subtitle_position_combo.setCurrentIndex(window.subtitle_position_combo.findData(window.config.subtitle_position.__class__.BOTTOM_LEFT))
    settle(lambda: window.subtitle_x_spin.value() == round(24 * 1920 / 1584))
    assert window.config.subtitle_x is None


def test_exportar_con_coordenadas_escritas_deja_el_subtitulo_ahi(window, tmp_path):
    window.subtitle_x_spin.setValue(640)
    window.subtitle_y_spin.setValue(480)
    window._on_generate_clicked()
    img = Image.open(tmp_path / "salida.png").convert("RGB")
    y = round(480 + window._build_subtitle_layout().rect.height / 2)
    assert img.getpixel((641, y)) == (0x2F, 0x80, 0xD6)          # el borde de 2 px, justo en X = 640
    assert img.getpixel((630, y)) != (0x2F, 0x80, 0xD6)


def test_el_grupo_subtitulo_no_es_mas_ancho_que_los_demas(window):
    """Regresion: las filas nuevas (coordenadas y botones de empuje) hicieron el grupo mas ancho que el panel y se
    recortaba por la derecha. Se compara contra los otros grupos (no contra un numero fijo, que cambia con las
    fuentes de cada plataforma)."""
    from PySide6.QtWidgets import QGroupBox

    anchos = {g.title(): g.minimumSizeHint().width() for g in window.findChildren(QGroupBox)}
    otros = max(w for titulo, w in anchos.items() if titulo != "Subtitulo")
    assert anchos["Subtitulo"] <= otros + 20, anchos
