"""Limpieza de titulos: deteccion de slug, Title Case en espanol y word wrap
balanceado. Sin dependencias de Qt para poder testear y usar desde CLI."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

MINOR_WORDS: frozenset[str] = frozenset({
    "de", "del", "la", "las", "el", "los", "y", "e", "o", "u", "en", "con",
    "para", "por", "a", "al", "un", "una", "que", "sin", "sobre",
})

_LETTER_RE = re.compile(r"[a-zA-Zà-üÀ-Üñÿ]")
_STRIP_PUNCT_RE = re.compile(r"^[^a-zA-Zà-üÀ-Üñÿ]+|[^a-zA-Zà-üÀ-Üñÿ]+$")


def looks_like_slug(title: str) -> bool:
    """True si el titulo parece un slug de URL: dos o mas guiones y sin espacios."""
    if " " in title:
        return False
    return title.count("-") >= 2


def slug_to_words(title: str) -> str:
    """Reemplaza cada guion por un espacio."""
    return title.replace("-", " ")


def _bare_word(word: str) -> str:
    """Quita puntuacion en los extremos (¿, ¡, :, [, ], etc.) para comparar contra MINOR_WORDS."""
    return _STRIP_PUNCT_RE.sub("", word)


def _capitalize_word(word: str) -> str:
    """Capitaliza la primera letra del token, respetando puntuacion inicial (¿cómo -> ¿Cómo)."""
    match = _LETTER_RE.search(word)
    if match is None:
        return word
    idx = match.start()
    return word[:idx] + word[idx].upper() + word[idx + 1:]


def to_title_case_es(text: str) -> str:
    """Convierte a Title Case en espanol respetando MINOR_WORDS salvo en la
    primera o ultima palabra. Si el texto ya trae mayusculas mezcladas, se
    devuelve intacto (regla 2 del documento)."""
    if text != text.lower():
        return text
    words = text.split(" ")
    last_index = len(words) - 1
    result: list[str] = []
    for i, word in enumerate(words):
        if not word:
            result.append(word)
            continue
        if i not in (0, last_index) and _bare_word(word) in MINOR_WORDS:
            result.append(word)
        else:
            result.append(_capitalize_word(word))
    return " ".join(result)


def normalize_title(title: str) -> str:
    """Punto de entrada: detecta slug y aplica Title Case segun las reglas del documento."""
    working = title.strip()
    if looks_like_slug(working):
        working = slug_to_words(working)
    return to_title_case_es(working)


MeasureFn = Callable[[str, float], float]


@dataclass(frozen=True)
class WrapResult:
    """Resultado de partir un titulo en lineas.

    fits es False cuando ni el maximo de lineas ni la reduccion de fuente
    (si auto_fit esta activo) lograron que el texto quepa en max_width; la UI
    debe mostrar una advertencia en vez de desbordar la banda en silencio.
    """

    lines: list[str]
    font_size: float
    fits: bool


def wrap_title(
    text: str,
    measure: MeasureFn,
    max_width: float,
    initial_font_size: float,
    max_lines: int = 2,
    auto_fit: bool = True,
    min_font_size: float = 24.0,
) -> WrapResult:
    """Balancea el titulo en como maximo max_lines lineas, sin cortar
    palabras. Si auto_fit esta encendido y no cabe, reduce el tamano de
    fuente (de 2 en 2 px) hasta min_font_size."""
    words = text.split()
    if not words:
        return WrapResult(lines=[""], font_size=initial_font_size, fits=True)

    font_size = initial_font_size
    lines = _wrap_at_size(text, measure, max_width, font_size, max_lines)
    while lines is None and auto_fit and font_size > min_font_size:
        font_size = max(min_font_size, font_size - 2)
        lines = _wrap_at_size(text, measure, max_width, font_size, max_lines)

    if lines is not None:
        return WrapResult(lines=lines, font_size=font_size, fits=True)

    fallback = _split_balanced(words, max_lines, measure, font_size) or [text]
    return WrapResult(lines=fallback, font_size=font_size, fits=False)


def _wrap_at_size(
    text: str,
    measure: MeasureFn,
    max_width: float,
    font_size: float,
    max_lines: int,
) -> list[str] | None:
    """Intenta partir el texto en <= max_lines lineas balanceadas que quepan
    en max_width a un tamano de fuente fijo. None si no cabe en ninguna
    cantidad de lineas permitida."""
    if measure(text, font_size) <= max_width:
        return [text]

    words = text.split()
    for n in range(2, max_lines + 1):
        candidate = _split_balanced(words, n, measure, font_size)
        if candidate is None:
            continue
        if all(measure(line, font_size) <= max_width for line in candidate):
            return candidate
    return None


def _split_balanced(
    words: Sequence[str],
    n_lines: int,
    measure: MeasureFn,
    font_size: float,
) -> list[str] | None:
    """Particion en n_lines lineas contiguas (sin cortar palabras) que
    minimiza el ancho maximo de linea. None si hay menos palabras que
    lineas pedidas."""
    words = list(words)
    if n_lines <= 0 or len(words) < n_lines:
        return None
    if n_lines == 1:
        return [" ".join(words)]

    n = len(words)
    widths = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i in range(n):
        for j in range(i + 1, n + 1):
            widths[i][j] = measure(" ".join(words[i:j]), font_size)

    inf = float("inf")
    dp = [[inf] * (n_lines + 1) for _ in range(n + 1)]
    choice = [[0] * (n_lines + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(1, n_lines + 1):
        for i in range(k, n + 1):
            for j in range(k - 1, i):
                prev = dp[j][k - 1]
                if prev == inf:
                    continue
                cost = max(prev, widths[j][i])
                if cost < dp[i][k]:
                    dp[i][k] = cost
                    choice[i][k] = j

    if dp[n][n_lines] == inf:
        return None

    lines: list[str] = []
    i, k = n, n_lines
    while k > 0:
        j = choice[i][k]
        lines.append(" ".join(words[j:i]))
        i, k = j, k - 1
    lines.reverse()
    return lines
