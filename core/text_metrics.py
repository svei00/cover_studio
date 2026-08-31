"""Medicion de texto con Pillow/FreeType, sin Qt: una MeasureFn para wrap_title y para las
animaciones, que se exportan desde un hilo aparte (QFontMetricsF no es seguro fuera del
hilo principal) y para usar desde CLI y tests.

NO es mas precisa que Qt. Medido contra el ancho de tinta que dibuja resvg (Georgia, 78 px,
6 cadenas): error absoluto medio de 0.77 px con QFontMetricsF vs 2.4 px (negrita) a 3.8 px
(regular) con Pillow. Pillow sin raqm no aplica kerning (GPOS) y por eso siempre SOBREESTIMA
unos px (0.2-0.5% del ancho). Es un error conservador: el wrap deja un poco mas de margen,
nunca desborda la banda. Para la UI interactiva Qt sigue siendo la medicion mas exacta."""

from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont, features

from core.text_utils import MeasureFn

# Familia (en minusculas) -> (archivo regular, archivo negrita). Pillow resuelve estos
# nombres contra las carpetas de fuentes del sistema (en Windows, C:\Windows\Fonts).
FONT_FILES: dict[str, tuple[str, str]] = {
    "georgia": ("georgia.ttf", "georgiab.ttf"),
    "times new roman": ("times.ttf", "timesbd.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "dejavu sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "dejavu serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    # familias genericas de CSS y equivalentes habituales
    "serif": ("times.ttf", "timesbd.ttf"),
    "sans-serif": ("arial.ttf", "arialbd.ttf"),
    "helvetica": ("arial.ttf", "arialbd.ttf"),
    "liberation sans": ("arial.ttf", "arialbd.ttf"),
}

_FALLBACK_EM = {True: 0.58, False: 0.52}  # ancho medio por caracter, en em (negrita, normal)

# Se mide a un tamano grande y se escala de forma lineal. Un SVG se rasteriza sin hinting
# (layout escalable), mientras que FreeType, a tamanos chicos, redondea el tamano a entero
# (77.4 y 78 dan distinto, 77.5 igual que 78) y las metricas a pixeles. Medido con Georgia a
# 78 px: 854.0 con hinting vs 855.7 escalando desde 512.
REFERENCE_SIZE = 512


def parse_families(font_family: str) -> list[str]:
    """'Georgia, 'Times New Roman', serif' -> ['georgia', 'times new roman', 'serif']."""
    return [name.strip().strip("'\"").strip().lower() for name in font_family.split(",") if name.strip()]


@lru_cache(maxsize=64)
def _can_load(filename: str) -> bool:
    try:
        ImageFont.truetype(filename, 12)
    except OSError:
        return False
    return True


def resolve_font_file(font_family: str, bold: bool) -> str | None:
    """Primer archivo de fuente disponible para la lista de familias (en el orden
    dado, como haria CSS). None si ninguna se encuentra en el sistema."""
    for family in parse_families(font_family):
        files = FONT_FILES.get(family)
        if files is None:
            continue
        filename = files[1] if bold else files[0]
        if _can_load(filename):
            return filename
    return None


def _layout_engine() -> ImageFont.Layout:
    """RAQM (con kerning GPOS, como resvg) si Pillow lo trae; si no, BASIC, que NO
    aplica kerning: sobreestima unos px en pares como AV o To."""
    return ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC


@lru_cache(maxsize=16)
def _reference_font(filename: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(filename, REFERENCE_SIZE, layout_engine=_layout_engine())


def heuristic_measure_fn(font_family: str, bold: bool) -> MeasureFn:
    """Ultimo recurso cuando la fuente no se encuentra: ancho medio por caracter.
    Es solo una aproximacion; sirve para no fallar, no para alinear con precision."""
    factor = _FALLBACK_EM[bool(bold)]

    def measure(text: str, size: float) -> float:
        return len(text) * size * factor

    return measure


def pillow_measure_fn(font_family: str, bold: bool) -> MeasureFn:
    """MeasureFn (texto, tamano_px) -> ancho_px basada en FreeType. Acepta tamanos
    fraccionarios. Tiene kerning solo si Pillow trae raqm (ver _layout_engine). Si la
    fuente no se resuelve, cae a la heuristica en vez de fallar."""
    filename = resolve_font_file(font_family, bold)
    if filename is None:
        return heuristic_measure_fn(font_family, bold)

    def measure(text: str, size: float) -> float:
        if not text:
            return 0.0
        return float(_reference_font(filename).getlength(text)) * size / REFERENCE_SIZE

    return measure
