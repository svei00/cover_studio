import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.geometry import (
    CanvasSize,
    CoverConfig,
    SubtitlePosition,
    build_svg,
    compute_subtitle_layout,
    render_png,
    render_png_bytes,
)
from core.presets import config_from_dict, config_to_dict, load_preset, save_preset
from core.text_metrics import pillow_measure_fn

PRESET_DEFAULT = Path(__file__).resolve().parent.parent / "presets" / "default.json"


def measure(text: str, size: float) -> float:
    """Medida determinista para los tests de geometria: 0.5 em por caracter."""
    return len(text) * size * 0.5


# --- configuracion y presets ---------------------------------------------------------

def test_los_defaults_son_los_pedidos():
    c = CoverConfig()
    assert (c.subtitle_text_color, c.subtitle_bg_color, c.subtitle_border_color) == ("#F1EBDF", "#1B3350", "#2F80D6")
    assert (c.subtitle_bg_opacity, c.subtitle_border_width) == (0.90, 2.0)
    assert c.subtitle_position is SubtitlePosition.BOTTOM_RIGHT and 0 < c.subtitle_font_size < c.font_size


def test_los_valores_del_subtitulo_se_guardan_y_se_recuperan(tmp_path):
    c = replace(
        CoverConfig(), subtitle_position=SubtitlePosition.BOTTOM_CENTER, subtitle_text_color="#111111",
        subtitle_bg_color="#222222", subtitle_bg_opacity=0.6, subtitle_border_color="#333333",
        subtitle_border_width=4.0, subtitle_font_size=44.0,
    )
    assert config_from_dict(config_to_dict(c)) == c
    assert load_preset(save_preset(c, "con-subtitulo", tmp_path)) == c
    assert json.loads((tmp_path / "con-subtitulo.json").read_text(encoding="utf-8"))["subtitle_position"] == "bottom-center"


def test_un_preset_viejo_sin_claves_del_subtitulo_abre_con_los_defaults():
    viejo = config_to_dict(CoverConfig(band_color="#ABCDEF"))
    for key in [k for k in viejo if k.startswith("subtitle_")]:
        del viejo[key]
    c = config_from_dict(viejo)
    assert c.band_color == "#ABCDEF"
    assert c.subtitle_position is SubtitlePosition.BOTTOM_RIGHT and c.subtitle_bg_opacity == 0.90


def test_una_posicion_desconocida_usa_la_de_siempre():
    c = config_from_dict({"subtitle_position": "arriba-al-centro"})
    assert c.subtitle_position is SubtitlePosition.BOTTOM_RIGHT


def test_el_preset_incluido_sigue_cargando():
    c = load_preset(PRESET_DEFAULT)
    assert c.band_color == "#21B868" and c.subtitle_border_width == 2.0


# --- layout ----------------------------------------------------------------------------

def _layout(text, **overrides):
    return compute_subtitle_layout(replace(CoverConfig(canvas=CanvasSize(1584, 891)), **overrides), text, measure)


def test_vacio_o_solo_espacios_no_dibuja_nada():
    assert _layout("") is None and _layout("   \t ") is None


def test_el_texto_se_respeta_como_se_escribe():
    assert _layout("hola mundo").lines == ("hola mundo",)
    assert _layout("iPhone en Excel").lines == ("iPhone en Excel",)   # ni mayusculas ni Title Case
    assert _layout("  varios   espacios  ").lines == ("varios espacios",)


def test_posicion_por_defecto_abajo_derecha_con_margen_de_24_px_a_1584():
    s = _layout("Subtitulo")
    r = s.rect
    assert r.x + r.width == pytest.approx(1584 - 24) and r.y + r.height == pytest.approx(891 - 24)


def test_el_margen_escala_con_el_ancho_del_lienzo():
    for width in (792, 1584, 1920, 3168):
        c = CoverConfig(canvas=CanvasSize(width, 900))
        r = compute_subtitle_layout(c, "Subtitulo", measure).rect
        assert width - (r.x + r.width) == pytest.approx(24 * width / 1584)


def test_abajo_izquierda_y_abajo_centro():
    izq = _layout("Subtitulo", subtitle_position=SubtitlePosition.BOTTOM_LEFT).rect
    assert izq.x == pytest.approx(24)
    centro = _layout("Subtitulo", subtitle_position=SubtitlePosition.BOTTOM_CENTER).rect
    assert centro.x + centro.width / 2 == pytest.approx(1584 / 2)
    assert centro.y == izq.y   # las tres van pegadas abajo


def test_el_ancho_se_ajusta_al_texto_mas_el_relleno():
    s = _layout("Hola", subtitle_font_size=40.0)
    assert s.font_size == 40.0
    assert s.rect.width == pytest.approx(measure("Hola", 40.0) + 2 * 0.9 * 40.0)
    assert s.rect.height == pytest.approx(1.2 * 40.0 + 2 * 0.5 * 40.0)
    corto, largo = _layout("Hola").rect.width, _layout("Hola, esto es mas largo").rect.width
    assert largo > corto


def test_el_radio_es_el_de_un_rectangulo_redondeado():
    s = _layout("Hola", subtitle_font_size=40.0)
    assert 0 < s.radius <= s.rect.height / 2


def test_si_no_cabe_en_una_linea_se_parte_en_dos():
    texto = "una frase bastante larga para el subtitulo de una portada del canal de contabilidad y excel para todos"
    s = _layout(texto, subtitle_font_size=40.0)
    assert len(s.lines) == 2 and " ".join(s.lines) == texto
    assert s.font_size == 40.0   # con dos lineas cabe sin achicar


def test_si_en_dos_lineas_no_cabe_se_achica_la_letra():
    texto = " ".join(["palabra"] * 40)
    s = _layout(texto, subtitle_font_size=40.0)
    assert s.font_size < 40.0 and len(s.lines) == 2


def test_nunca_se_sale_del_lienzo_ni_con_una_palabra_enorme():
    for texto in ("x" * 400, "ab " * 300, "Subtitulo"):
        for pos in SubtitlePosition:
            for size in (12.0, 36.0, 120.0):
                c = CoverConfig(canvas=CanvasSize(800, 450), subtitle_position=pos, subtitle_font_size=size)
                s = compute_subtitle_layout(c, texto, measure)
                r = s.rect
                assert r.x >= 0 and r.y >= 0 and r.x + r.width <= 800 + 1e-6 and r.y + r.height <= 450 + 1e-6, (texto[:8], pos, size)


# --- SVG ------------------------------------------------------------------------------------

LINES = ["Titulo"]


def _svg(text="Mi subtitulo", **overrides):
    config = replace(CoverConfig(), **overrides)
    return config, build_svg(config, LINES, 78.0, None, compute_subtitle_layout(config, text, measure))


def test_sin_subtitulo_el_svg_es_exactamente_el_de_siempre():
    config = CoverConfig()
    assert build_svg(config, LINES, 78.0) == build_svg(config, LINES, 78.0, None, None)
    assert "#1B3350" not in build_svg(config, LINES, 78.0)
    assert build_svg(config, LINES, 78.0) == build_svg(config, LINES, 78.0, subtitle=compute_subtitle_layout(config, "", measure))


def test_el_subtitulo_es_un_solo_rectangulo_sin_capa_doble_ni_sombra():
    config, svg = _svg("Mi subtitulo")
    assert len(re.findall(r'<rect[^>]*fill="#1B3350"', svg)) == 1
    assert svg.count("<path") == 1                       # solo el acento en L del titulo
    sub_text = re.search(r'<text[^>]*>Mi subtitulo</text>', svg).group(0)
    assert "filter=" not in sub_text and "opacity" not in sub_text and 'fill="#F1EBDF"' in sub_text
    assert "Mi subtitulo" in svg


def test_la_opacidad_es_solo_del_relleno():
    config, svg = _svg("Mi subtitulo", subtitle_bg_opacity=0.6, subtitle_border_width=4.0)
    rect = re.search(r'<rect[^>]*fill="#1B3350"[^>]*/>', svg).group(0)
    assert 'fill-opacity="0.60"' in rect
    assert 'stroke="#2F80D6"' in rect and 'stroke-width="4.00"' in rect and "stroke-opacity" not in rect
    assert "opacity" not in re.search(r'<text[^>]*>Mi subtitulo</text>', svg).group(0)


def test_con_borde_cero_no_hay_trazo():
    config, svg = _svg("Mi subtitulo", subtitle_border_width=0.0)
    rect = re.search(r'<rect[^>]*fill="#1B3350"[^>]*/>', svg).group(0)
    assert "stroke" not in rect


def test_el_borde_y_la_opacidad_se_acotan():
    _, svg = _svg("Mi subtitulo", subtitle_border_width=99.0, subtitle_bg_opacity=7.0)
    rect = re.search(r'<rect[^>]*fill="#1B3350"[^>]*/>', svg).group(0)
    assert 'stroke-width="12.00"' in rect and 'fill-opacity="1.00"' in rect


def test_el_texto_del_subtitulo_se_escapa():
    _, svg = _svg("Excel & <Power> \"BI\"")
    assert "Excel &amp; &lt;Power&gt; &quot;BI&quot;" in svg


# --- pixeles: lo que sale en el PNG ------------------------------------------------------------------

def _render(tmp_path, name, **overrides):
    config = replace(CoverConfig(canvas=CanvasSize(1584, 891)), subtitle_font_size=48.0, **overrides)
    layout = compute_subtitle_layout(config, "Mi subtitulo de prueba", pillow_measure_fn(config.font_family, True))
    svg = build_svg(config, LINES, 78.0, None, layout)
    out = tmp_path / name
    render_png(svg, out, config.canvas.width, config.canvas.height)
    return Image.open(out).convert("RGB"), layout


def _blend(fg, bg, alpha):
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


def test_opacidad_60_y_grosor_4_en_el_png(tmp_path):
    img, layout = _render(tmp_path, "op60.png", subtitle_bg_opacity=0.6, subtitle_border_width=4.0)
    r = layout.rect
    fondo_neutro = (0x6E, 0x6E, 0x6E)                  # lo que hay detras: el gris neutro del lienzo
    navy = (0x1B, 0x33, 0x50)
    relleno = img.getpixel((round(r.x + 12), round(r.y + r.height / 2)))
    esperado = _blend(navy, fondo_neutro, 0.6)
    assert all(abs(a - b) <= 2 for a, b in zip(relleno, esperado)), (relleno, esperado)
    # el borde de 4 px, a mitad de la arista izquierda, esta al 100 %: el color exacto, sin mezclarse con el fondo
    borde = img.getpixel((round(r.x + 2), round(r.y + r.height / 2)))
    assert borde == (0x2F, 0x80, 0xD6)
    # y mas hacia adentro que el borde ya es relleno
    assert img.getpixel((round(r.x + 8), round(r.y + r.height / 2))) != borde


def test_el_texto_se_dibuja_al_100_aunque_la_opacidad_sea_baja(tmp_path):
    img, layout = _render(tmp_path, "op10.png", subtitle_bg_opacity=0.1, subtitle_border_width=4.0)
    r = layout.rect
    caja = img.crop((round(r.x), round(r.y), round(r.x + r.width), round(r.y + r.height)))
    texto = dict((c, n) for n, c in caja.getcolors(maxcolors=1_000_000)).get((0xF1, 0xEB, 0xDF), 0)
    assert texto > 150    # hay pixeles del color exacto del texto: no se mezcla con la opacidad del fondo


def test_con_grosor_0_no_hay_borde_en_el_png(tmp_path):
    con, layout = _render(tmp_path, "con.png", subtitle_border_width=4.0)
    sin, _ = _render(tmp_path, "sin.png", subtitle_border_width=0.0)
    r = layout.rect
    p = (round(r.x + 2), round(r.y + r.height / 2))
    assert con.getpixel(p) == (0x2F, 0x80, 0xD6)
    assert sin.getpixel(p) != (0x2F, 0x80, 0xD6)
    azules = dict((c, n) for n, c in sin.getcolors(maxcolors=1_000_000)).get((0x2F, 0x80, 0xD6), 0)
    assert azules == 0     # ni un solo pixel del color del borde


def test_el_grosor_no_cambia_el_tamano_ni_la_posicion_de_la_franja(tmp_path):
    a, la = _render(tmp_path, "a.png", subtitle_border_width=0.0)
    b, lb = _render(tmp_path, "b.png", subtitle_border_width=12.0)
    assert la.rect == lb.rect   # el borde crece hacia adentro


def test_la_vista_previa_y_la_exportacion_dan_los_mismos_pixeles(tmp_path):
    config = replace(CoverConfig(), subtitle_bg_opacity=0.6, subtitle_border_width=4.0)
    layout = compute_subtitle_layout(config, "Mi subtitulo", measure)
    svg = build_svg(config, LINES, 78.0, None, layout)
    out = tmp_path / "export.png"
    render_png(svg, out, config.canvas.width, config.canvas.height)
    assert out.read_bytes() == render_png_bytes(svg, config.canvas.width, config.canvas.height)   # un solo camino
