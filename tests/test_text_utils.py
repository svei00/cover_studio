from core.text_utils import (
    looks_like_slug,
    normalize_title,
    slug_to_words,
    to_title_case_es,
    wrap_title,
)


def char_measure(text: str, size: float) -> float:
    """Medidor de prueba: ancho proporcional a la cantidad de caracteres, sin Qt."""
    return len(text) * size * 0.5


# --- slug ---------------------------------------------------------------

def test_looks_like_slug_true_con_varios_guiones():
    assert looks_like_slug("tabla-excel-encabezados-columna") is True


def test_looks_like_slug_false_con_un_solo_guion():
    assert looks_like_slug("auto-evaluacion") is False


def test_looks_like_slug_false_si_hay_espacios():
    assert looks_like_slug("tabla - excel - tips") is False


def test_slug_to_words_reemplaza_guiones():
    assert slug_to_words("tabla-excel-encabezados") == "tabla excel encabezados"


def test_normalize_title_convierte_slug_y_aplica_title_case():
    result = normalize_title("tabla-excel-encabezados-columna")
    assert result == "Tabla Excel Encabezados Columna"


# --- title case español --------------------------------------------------

def test_title_case_capitaliza_palabras_mayores():
    result = to_title_case_es("como usar tablas dinamicas de excel")
    assert result == "Como Usar Tablas Dinamicas de Excel"


def test_title_case_minusculiza_palabras_menores_intermedias():
    result = to_title_case_es("el arte de la contabilidad")
    assert result == "El Arte de la Contabilidad"


def test_title_case_capitaliza_palabra_menor_al_inicio_y_final():
    result = to_title_case_es("de vuelta a la")
    assert result.split(" ")[0] == "De"
    assert result.split(" ")[-1] == "La"


def test_title_case_no_toca_texto_con_mayusculas_mezcladas():
    original = "Como Usar Excel En 2026"
    assert to_title_case_es(original) == original


def test_title_case_preserva_acentos_y_puntuacion():
    result = to_title_case_es("¿como se hace? [guia rapida]")
    assert result.startswith("¿Como")
    assert "[Guia" in result


# --- word wrap balanceado -------------------------------------------------

def test_wrap_title_una_linea_si_cabe():
    result = wrap_title(
        "Excel Basico",
        measure=char_measure,
        max_width=1000,
        initial_font_size=78,
        max_lines=2,
    )
    assert result.lines == ["Excel Basico"]
    assert result.fits is True


def test_wrap_title_parte_en_dos_lineas_balanceadas():
    text = "Tabla Excel Encabezados Columna Dinamica"
    result = wrap_title(
        text,
        measure=char_measure,
        max_width=char_measure("Tabla Excel Encabezados", 78) + 1,
        initial_font_size=78,
        max_lines=2,
    )
    assert len(result.lines) == 2
    assert " ".join(result.lines).split() == text.split()
    larger, smaller = sorted((len(result.lines[0]), len(result.lines[1])), reverse=True)
    assert larger - smaller <= max(len(w) for w in text.split()) + 2


def test_wrap_title_no_corta_palabras():
    text = "Contabilidad Fiscal Para Pequenas Empresas Mexicanas"
    result = wrap_title(
        text,
        measure=char_measure,
        max_width=char_measure("Contabilidad Fiscal Para", 78),
        initial_font_size=78,
        max_lines=3,
    )
    rebuilt = " ".join(result.lines).split()
    assert rebuilt == text.split()


def test_wrap_title_reduce_fuente_si_auto_fit_esta_activo():
    text = "Un Titulo Extremadamente Largo Que Nunca Cabria En Una Banda Angosta De Portada"
    result = wrap_title(
        text,
        measure=char_measure,
        max_width=300,
        initial_font_size=78,
        max_lines=2,
        auto_fit=True,
        min_font_size=24,
    )
    assert result.font_size < 78
    assert result.font_size >= 24


def test_wrap_title_marca_fits_false_sin_auto_fit_si_no_cabe():
    text = "Un Titulo Extremadamente Largo Que Nunca Cabria En Una Banda Angosta De Portada"
    result = wrap_title(
        text,
        measure=char_measure,
        max_width=300,
        initial_font_size=78,
        max_lines=2,
        auto_fit=False,
    )
    assert result.fits is False
    assert result.font_size == 78
