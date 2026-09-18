import os
import re
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PIL import Image

from core.geometry import CanvasSize, CoverConfig, GradientDirection, build_svg, compute_subtitle_layout, render_png
from core.presets import config_from_dict, config_to_dict, load_preset, save_preset


def measure(text: str, size: float) -> float:
    return len(text) * size * 0.5


def _svg(**overrides):
    config = replace(CoverConfig(), **overrides)
    return build_svg(config, ["Titulo"], 78.0, None, compute_subtitle_layout(config, "Mi subtitulo", measure))


def _sub_rect(svg):
    return re.search(r'<rect[^>]*(?:fill="#1B3350"|subtitleGradient)[^>]*/>', svg).group(0)


# --- configuracion ---------------------------------------------------------------------------

def test_los_defaults_del_borde_en_degradado():
    c = CoverConfig()
    assert c.subtitle_border_gradient is False and c.subtitle_border_color2 == "#21B868"   # el verde de la banda


def test_se_guarda_y_se_recupera(tmp_path):
    c = replace(CoverConfig(), subtitle_border_gradient=True, subtitle_border_color="#112233", subtitle_border_color2="#445566")
    assert config_from_dict(config_to_dict(c)) == c
    assert load_preset(save_preset(c, "borde", tmp_path)) == c


def test_un_preset_viejo_abre_sin_degradado_en_el_borde():
    assert config_from_dict({"subtitle_gradient": True}).subtitle_border_gradient is False


@pytest.mark.parametrize("data,campo,esperado", [
    ({"subtitle_border_color2": "verde"}, "subtitle_border_color2", "#21B868"),
    ({"subtitle_border_color2": 3}, "subtitle_border_color2", "#21B868"),
    ({"subtitle_border_gradient": "si"}, "subtitle_border_gradient", False),
    ({"subtitle_border_gradient": 1}, "subtitle_border_gradient", False),
])
def test_un_dato_danado_usa_el_de_siempre(data, campo, esperado):
    assert getattr(config_from_dict(data), campo) == esperado


# --- SVG -------------------------------------------------------------------------------------------

def test_sin_degradado_en_el_borde_el_borde_es_un_color_solido():
    svg = _svg()
    assert "subtitleBorderGradient" not in svg and 'stroke="#2F80D6"' in _sub_rect(svg)


def test_el_borde_en_degradado_tiene_su_propio_gradiente_de_dos_colores():
    svg = _svg(subtitle_border_gradient=True, subtitle_border_color="#3182DF", subtitle_border_color2="#21B868",
               subtitle_border_width=4.0)
    grad = re.search(r'<linearGradient id="subtitleBorderGradient"[^>]*>(.*?)</linearGradient>', svg).group(1)
    assert re.findall(r'stop offset="(\d)" stop-color="(#\w+)"', grad) == [("0", "#3182DF"), ("1", "#21B868")]
    rect = _sub_rect(svg)
    assert 'stroke="url(#subtitleBorderGradient)"' in rect and 'stroke-width="4.00"' in rect
    assert 'fill="#1B3350"' in rect                       # el relleno no cambio
    assert "stroke-opacity" not in rect                   # y el borde sigue al 100 %
    assert "subtitleGradient" not in svg                  # no hay degradado de relleno


def test_relleno_y_borde_en_degradado_a_la_vez_son_dos_gradientes_independientes():
    svg = _svg(subtitle_gradient=True, subtitle_border_gradient=True, subtitle_bg_color="#21B868", subtitle_bg_color2="#3182DF",
               subtitle_border_color="#3182DF", subtitle_border_color2="#21B868")
    assert svg.count("<linearGradient") == 2
    assert svg.count("subtitleGradient") >= 2 and svg.count("subtitleBorderGradient") >= 2   # cada uno definido y usado
    fondo = re.search(r'<linearGradient id="subtitleGradient"[^>]*>(.*?)</linearGradient>', svg).group(1)
    borde = re.search(r'<linearGradient id="subtitleBorderGradient"[^>]*>(.*?)</linearGradient>', svg).group(1)
    assert re.findall(r'stop-color="(#\w+)"', fondo) == ["#21B868", "#3182DF"]
    assert re.findall(r'stop-color="(#\w+)"', borde) == ["#3182DF", "#21B868"]    # al reves: el borde se distingue
    rect = re.search(r'<rect[^>]*subtitleGradient[^>]*/>', svg).group(0)
    assert 'fill="url(#subtitleGradient)"' in rect and 'stroke="url(#subtitleBorderGradient)"' in rect


@pytest.mark.parametrize("direccion,vector", [
    (GradientDirection.HORIZONTAL, ("0", "0", "1", "0")),
    (GradientDirection.VERTICAL, ("0", "0", "0", "1")),
    (GradientDirection.DIAGONAL, ("0", "0", "1", "1")),
])
def test_el_borde_usa_la_misma_direccion_que_el_relleno(direccion, vector):
    svg = _svg(subtitle_border_gradient=True, subtitle_gradient_direction=direccion)
    m = re.search(r'<linearGradient id="subtitleBorderGradient" x1="(\d)" y1="(\d)" x2="(\d)" y2="(\d)"', svg)
    assert m.groups() == vector


def test_con_grosor_cero_no_hay_borde_ni_gradiente_de_borde():
    svg = _svg(subtitle_border_gradient=True, subtitle_border_width=0.0)
    assert "subtitleBorderGradient" not in svg and "stroke=" not in _sub_rect(svg)


def test_el_texto_no_cambia_con_el_borde_en_degradado():
    texto = re.search(r'<text[^>]*>Mi subtitulo</text>', _svg(subtitle_border_gradient=True)).group(0)
    assert "stroke" not in texto and 'fill="#F1EBDF"' in texto


# --- pixeles: lo que sale en el PNG ----------------------------------------------------------------------

RADIO = 0.4 * 48


def _render(tmp_path, name, **overrides):
    opciones = {"subtitle_font_size": 48.0, "subtitle_border_width": 8.0, "subtitle_bg_opacity": 1.0, **overrides}
    config = replace(CoverConfig(canvas=CanvasSize(1584, 891)), **opciones)
    layout = compute_subtitle_layout(config, "Borde degradado", measure)
    out = tmp_path / name
    render_png(build_svg(config, ["T"], 78.0, None, layout), out, 1584, 891)
    return Image.open(out).convert("RGB"), layout.rect


def _cerca(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _borde(img, r):
    """Pixeles del borde de ARRIBA (4 px adentro del canto), pasada la esquina redondeada: a la izquierda y a la derecha."""
    y = round(r.y + 3)
    return img.getpixel((round(r.x + RADIO + 6), y)), img.getpixel((round(r.x + r.width - RADIO - 6), y))


def test_el_borde_cambia_de_color_de_un_extremo_al_otro_en_el_png(tmp_path):
    img, r = _render(tmp_path, "g.png", subtitle_border_gradient=True, subtitle_border_color="#FF0000",
                     subtitle_border_color2="#0000FF")
    izq, der = _borde(img, r)
    assert _cerca(izq, (255, 0, 0)) and _cerca(der, (0, 0, 255))
    assert izq[0] > der[0] and der[2] > izq[2]


def test_sin_degradado_el_borde_es_del_mismo_color_en_los_dos_extremos(tmp_path):
    img, r = _render(tmp_path, "s.png", subtitle_border_color="#FF0000")
    izq, der = _borde(img, r)
    assert izq == der == (255, 0, 0)


def test_el_borde_en_degradado_va_al_100_aunque_el_fondo_sea_translucido(tmp_path):
    img, r = _render(tmp_path, "op.png", subtitle_border_gradient=True, subtitle_border_color="#FF0000",
                     subtitle_border_color2="#FF0000", subtitle_bg_opacity=0.2)
    izq, der = _borde(img, r)
    assert izq == der == (255, 0, 0)                      # los dos colores iguales: rojo puro, sin mezclarse con el fondo


def test_borde_y_relleno_en_degradado_son_independientes_en_el_png(tmp_path):
    img, r = _render(tmp_path, "ambos.png", subtitle_gradient=True, subtitle_bg_color="#00FF00", subtitle_bg_color2="#FFFF00",
                     subtitle_border_gradient=True, subtitle_border_color="#FF0000", subtitle_border_color2="#0000FF")
    izq, der = _borde(img, r)
    assert _cerca(izq, (255, 0, 0)) and _cerca(der, (0, 0, 255))                  # el borde: rojo -> azul
    y_fondo = round(r.y + 12)                                                      # dentro del relleno, debajo del borde de 8 px
    fondo_izq = img.getpixel((round(r.x + RADIO + 6), y_fondo))
    fondo_der = img.getpixel((round(r.x + r.width - RADIO - 6), y_fondo))
    assert fondo_izq[1] > 200 and fondo_izq[2] < 80 and fondo_der[0] > 150 and fondo_der[1] > 200   # el relleno: verde -> amarillo


def test_el_tamano_y_la_posicion_de_la_franja_no_cambian_con_el_degradado_del_borde(tmp_path):
    _, a = _render(tmp_path, "a.png")
    _, b = _render(tmp_path, "b.png", subtitle_border_gradient=True)
    assert a == b


# --- ventana ---------------------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


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


def test_los_controles_del_borde_arrancan_apagados_y_ocultos(window):
    assert not window.subtitle_border_gradient_checkbox.isChecked()
    assert window.subtitle_border_gradient_panel.isHidden() and window.subtitle_gradient_common_panel.isHidden()
    assert window.subtitle_border_color2_picker.hex_color().upper() == "#21B868"
    assert window.subtitle_border_gradient_checkbox.text() == "Degradado en el borde"
    assert window.subtitle_gradient_checkbox.text() == "Degradado en el relleno"


def test_encender_el_borde_en_degradado_muestra_sus_controles_y_los_comunes(window):
    window.subtitle_border_gradient_checkbox.setChecked(True)
    assert window.config.subtitle_border_gradient and not window.subtitle_border_gradient_panel.isHidden()
    assert not window.subtitle_gradient_common_panel.isHidden()          # la direccion sirve tambien al borde
    assert window.subtitle_gradient_panel.isHidden()                      # el relleno sigue sin degradado
    window.subtitle_border_color2_picker.set_hex_color("#445566")
    assert window.config.subtitle_border_color2 == "#445566"
    window.subtitle_border_gradient_checkbox.setChecked(False)
    assert window.subtitle_border_gradient_panel.isHidden() and window.subtitle_gradient_common_panel.isHidden()


def test_los_controles_comunes_se_ven_mientras_alguno_de_los_dos_este_encendido(window):
    window.subtitle_gradient_checkbox.setChecked(True)
    window.subtitle_border_gradient_checkbox.setChecked(True)
    window.subtitle_gradient_checkbox.setChecked(False)
    assert not window.subtitle_gradient_common_panel.isHidden()          # queda el del borde
    window.subtitle_border_gradient_checkbox.setChecked(False)
    assert window.subtitle_gradient_common_panel.isHidden()


def test_la_direccion_elegida_aplica_a_los_dos(window):
    window.subtitle_border_gradient_checkbox.setChecked(True)
    window.subtitle_gradient_direction_combo.setCurrentIndex(window.subtitle_gradient_direction_combo.findData(GradientDirection.VERTICAL))
    assert window.config.subtitle_gradient_direction is GradientDirection.VERTICAL


def test_el_boton_de_marca_sin_nada_encendido_enciende_los_dos(window):
    window.band_color_picker.set_hex_color("#21B868")
    window.accent_color_picker.set_hex_color("#3182DF")
    window.subtitle_brand_btn.click()
    c = window.config
    assert c.subtitle_gradient and c.subtitle_border_gradient
    assert (c.subtitle_bg_color.upper(), c.subtitle_bg_color2.upper()) == ("#21B868", "#3182DF")          # relleno: banda -> acento
    assert (c.subtitle_border_color.upper(), c.subtitle_border_color2.upper()) == ("#3182DF", "#21B868")   # borde: al reves


def test_el_boton_de_marca_solo_toca_lo_que_esta_encendido(window):
    window.subtitle_border_gradient_checkbox.setChecked(True)
    antes = (window.config.subtitle_bg_color, window.config.subtitle_bg_color2)
    window.subtitle_brand_btn.click()
    assert not window.config.subtitle_gradient                                                 # el relleno no se encendio
    assert (window.config.subtitle_bg_color, window.config.subtitle_bg_color2) == antes        # ni se cambiaron sus colores
    assert window.config.subtitle_border_color2.upper() == window.config.band_color.upper()


def test_los_controles_nuevos_reprograman_la_vista_previa(window):
    for accion in (
        lambda: window.subtitle_border_gradient_checkbox.setChecked(True),
        lambda: window.subtitle_border_color2_picker.set_hex_color("#102030"),
    ):
        window._preview_timer.stop()
        accion()
        assert window._preview_timer.isActive()


def test_un_preset_llena_los_controles_del_borde(window, tmp_path):
    c = replace(CoverConfig(), subtitle_border_gradient=True, subtitle_border_color2="#ABCDEF")
    window._apply_config_to_widgets(load_preset(save_preset(c, "p", tmp_path)))
    assert window.subtitle_border_gradient_checkbox.isChecked() and not window.subtitle_border_gradient_panel.isHidden()
    assert window.subtitle_border_color2_picker.hex_color().upper() == "#ABCDEF"
    assert not window.subtitle_gradient_common_panel.isHidden()
    window._apply_config_to_widgets(CoverConfig())
    assert window.subtitle_border_gradient_panel.isHidden() and window.subtitle_gradient_common_panel.isHidden()


def test_exportar_con_el_borde_en_degradado(window, tmp_path):
    window.subtitle_border_gradient_checkbox.setChecked(True)
    window.subtitle_border_color_picker.set_hex_color("#ff0000")
    window.subtitle_border_color2_picker.set_hex_color("#0000ff")
    window.subtitle_border_slider._spin.setValue(8.0)
    window._on_generate_clicked()
    img = Image.open(tmp_path / "salida.png").convert("RGB")
    r = window._build_subtitle_layout().rect
    y = round(r.y + 3)
    izq, der = img.getpixel((round(r.x + 0.4 * 36 + 6), y)), img.getpixel((round(r.x + r.width - 0.4 * 36 - 6), y))
    assert izq[0] > der[0] and der[2] > izq[2]
