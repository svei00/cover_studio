import io

import pytest
import resvg_py
from PIL import Image, ImageFont

from core import text_metrics
from core.text_metrics import (
    FONT_FILES,
    REFERENCE_SIZE,
    _reference_font,
    heuristic_measure_fn,
    parse_families,
    pillow_measure_fn,
    resolve_font_file,
)
from core.text_utils import wrap_title

GEORGIA_STACK = "Georgia, 'Times New Roman', serif"
needs_georgia = pytest.mark.skipif(
    resolve_font_file("Georgia", False) is None, reason="Georgia no esta instalada en este sistema"
)


def test_parse_families_quita_comillas_y_normaliza():
    assert parse_families(GEORGIA_STACK) == ["georgia", "times new roman", "serif"]
    assert parse_families("  'ARIAL' ,\"Segoe UI\" ") == ["arial", "segoe ui"]
    assert parse_families("") == []


def test_toda_familia_registrada_tiene_regular_y_negrita_distintas():
    for family, (regular, bold) in FONT_FILES.items():
        assert regular != bold, family


@needs_georgia
def test_resuelve_georgia_regular_y_negrita():
    assert resolve_font_file(GEORGIA_STACK, False) == "georgia.ttf"
    assert resolve_font_file(GEORGIA_STACK, True) == "georgiab.ttf"


@needs_georgia
def test_es_insensible_a_mayusculas_y_comillas_y_respeta_el_orden():
    assert resolve_font_file("'GEORGIA'", False) == "georgia.ttf"
    assert resolve_font_file("Fuente Inexistente, Georgia", False) == "georgia.ttf"  # salta la que no existe


def test_familia_desconocida_no_resuelve():
    assert resolve_font_file("Fuente Inexistente XYZ", False) is None
    assert resolve_font_file("", True) is None


def test_solo_la_generica_resuelve_a_su_equivalente_o_a_nada():
    assert resolve_font_file("Fuente Inexistente, serif", False) in (None, "times.ttf")


@needs_georgia
def test_los_anchos_de_georgia_coinciden_con_los_medidos():
    texto = "Contabilidad Electronica"
    regular = pillow_measure_fn("Georgia", False)(texto, 78)
    negrita = pillow_measure_fn("Georgia", True)(texto, 78)
    assert 820 < regular < 890   # medido: 854.0
    assert 960 < negrita < 1040  # medido: 1000.0
    assert negrita > regular


@needs_georgia
def test_el_ancho_escala_de_forma_lineal_con_el_tamano_y_crece_con_el_largo():
    measure = pillow_measure_fn("Georgia", False)
    assert measure("Excel", 156) == pytest.approx(2 * measure("Excel", 78), rel=1e-9)
    assert measure("Excel Solutions", 60) > measure("Excel", 60)
    assert measure("", 78) == 0.0


@needs_georgia
def test_acepta_tamanos_fraccionarios_sin_los_saltos_del_redondeo_de_freetype():
    measure = pillow_measure_fn("Georgia", False)
    # Pillow directo: 77.4 -> 183.0, 77.5 y 78 -> 185.0 (redondea el tamano). Aqui es suave.
    assert measure("Excel", 77.0) < measure("Excel", 77.4) < measure("Excel", 77.5) < measure("Excel", 78.0)


@needs_georgia
def test_mide_a_tamano_de_referencia_y_escala():
    measure = pillow_measure_fn("Georgia", False)
    font = ImageFont.truetype("georgia.ttf", REFERENCE_SIZE)
    assert measure("AVATAR To", 78) == pytest.approx(font.getlength("AVATAR To") * 78 / REFERENCE_SIZE)
    assert _reference_font("georgia.ttf") is _reference_font("georgia.ttf")  # una fuente por archivo


@needs_georgia
def test_se_acerca_al_ancho_sin_hinting_dentro_del_medio_por_ciento():
    texto = "Contabilidad Electronica"
    escalado = pillow_measure_fn("Georgia", False)(texto, 78)
    con_hinting = ImageFont.truetype("georgia.ttf", 78).getlength(texto)  # 854.0 medido
    assert escalado == pytest.approx(con_hinting, rel=0.005)


def test_usa_raqm_solo_si_pillow_lo_trae(monkeypatch):
    monkeypatch.setattr(text_metrics.features, "check", lambda name: name == "raqm")
    assert text_metrics._layout_engine() == ImageFont.Layout.RAQM
    monkeypatch.setattr(text_metrics.features, "check", lambda name: False)
    assert text_metrics._layout_engine() == ImageFont.Layout.BASIC


def test_sin_fuente_cae_a_la_heuristica_sin_lanzar():
    measure = pillow_measure_fn("Fuente Inexistente XYZ", False)
    heuristic = heuristic_measure_fn("Fuente Inexistente XYZ", False)
    assert measure("Hola mundo", 40) == heuristic("Hola mundo", 40) > 0


def test_la_heuristica_es_lineal_y_la_negrita_es_mas_ancha():
    regular, negrita = heuristic_measure_fn("x", False), heuristic_measure_fn("x", True)
    assert regular("abcd", 20) == pytest.approx(2 * regular("ab", 20))
    assert regular("abcd", 40) == pytest.approx(2 * regular("abcd", 20))
    assert negrita("abcd", 20) > regular("abcd", 20)
    assert regular("", 20) == 0.0


@needs_georgia
def test_funciona_como_measure_fn_de_wrap_title():
    measure = pillow_measure_fn(GEORGIA_STACK, True)
    titulo = "Conciliacion Bancaria Automatizada con Excel y Python para Despachos Contables"
    resultado = wrap_title(titulo, measure=measure, max_width=1500, initial_font_size=78, max_lines=2)
    assert resultado.fits and 1 <= len(resultado.lines) <= 2
    assert " ".join(resultado.lines).split() == titulo.split()
    assert all(measure(linea, resultado.font_size) <= 1500 for linea in resultado.lines)


@needs_georgia
def test_wrap_title_reduce_la_fuente_si_no_cabe():
    measure = pillow_measure_fn(GEORGIA_STACK, True)
    titulo = "Conciliacion Bancaria Automatizada con Excel y Python para Despachos Contables"
    resultado = wrap_title(titulo, measure=measure, max_width=700, initial_font_size=78, max_lines=2)
    assert resultado.font_size < 78


# --- contra lo que realmente dibuja resvg ---------------------------------------

def _resvg_ink_width(text: str, bold: bool, size: int = 78) -> float:
    """Ancho de la tinta que resvg dibuja para ese texto (lo que se exporta)."""
    weight = "700" if bold else "400"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="2600" height="200">'
        f'<text x="20" y="130" font-family="Georgia" font-size="{size}" font-weight="{weight}" '
        f'fill="#000">{text}</text></svg>'
    )
    png = resvg_py.svg_to_bytes(svg_string=svg, width=2600, height=200)
    alpha = Image.open(io.BytesIO(png)).convert("RGBA").split()[3]
    box = alpha.point(lambda v: 255 if v > 20 else 0).getbbox()
    return float(box[2] - box[0])


MUESTRAS = [
    "Contabilidad Electronica",
    "AVATAR To Yo",
    "Tabla Excel Encabezados Columna",
    "Deducciones Autorizadas RESICO 2026",
]


@needs_georgia
@pytest.mark.parametrize("bold", [False, True])
@pytest.mark.parametrize("texto", MUESTRAS)
def test_nunca_queda_por_debajo_de_lo_que_resvg_dibuja_y_no_se_pasa_mucho(texto, bold):
    """El ancho de avance incluye los espacios laterales de las letras (unos px), asi
    que debe ser >= la tinta; y como Pillow no aplica kerning se pasa unos px mas. El wrap
    queda del lado seguro: nunca mide menos de lo que se pinta."""
    medido = pillow_measure_fn("Georgia", bold)(texto, 78)
    tinta = _resvg_ink_width(texto, bold)
    assert medido >= tinta - 1.0, "mide MENOS de lo que resvg dibuja: el texto podria desbordar la banda"
    assert medido <= tinta + 0.01 * tinta + 12, "se pasa demasiado: el wrap partiria lineas que si caben"
