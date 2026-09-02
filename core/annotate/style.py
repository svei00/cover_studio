"""Constantes de identidad visual para las anotaciones. Los valores vienen de
Doc.marker() y Doc.step() en infographic_builder.py (skill excel-solutions-social);
se copian aqui porque el builder vive fuera del repo."""

from __future__ import annotations

GLOW_GOLD = "#E8B95C"
RED = "#621132"
CREAM = "#F1EBDF"
GOLD = "#B38E5D"
TAN = "#D4C19C"
CARD_FILL = "#1B3350"
PAGE_BG = "#14263A"
SUCCESS_FILL = "#123322"
SUCCESS_GREEN = "#21B868"

FONT = "Liberation Sans, Arial, Helvetica, sans-serif"

# El builder dibuja sobre un lienzo de ~1600 px; todo se escala contra ese ancho.
REFERENCE_WIDTH = 1600
MIN_SCALE = 0.5
MAX_SCALE = 4.0

# Anillos del resplandor: (separacion, opacidad), calibrados el 2026-09-02.
GLOW_RINGS: tuple[tuple[float, float], ...] = tuple(
    (i * 2.2, round(0.55 * (1 - i / 10.0) ** 1.6, 4)) for i in range(1, 10)
)
GLOW_RING_WIDTH = 4.5

# Resaltador: colores estandar de papeleria (medidos sobre fondo claro con Marcador y sobre
# fondo oscuro con Translucido, 2026-10).
HIGHLIGHT_YELLOW = "#FFF200"
HIGHLIGHT_SWATCHES: tuple[tuple[str, str], ...] = (
    ("Amarillo", HIGHLIGHT_YELLOW),
    ("Verde", "#7CFC00"),
    ("Rosa", "#FF69B4"),
    ("Naranja", "#FFA500"),
    ("Azul claro", "#00BFFF"),
)
HIGHLIGHT_RADIUS = 3.0          # esquinas del resaltador a escala 1
MAX_HIGHLIGHT_RADIUS = 30.0
HIGHLIGHT_MARKER_OPACITY = 1.0   # modo Marcador (multiplicar): el color puro, el texto sigue negro
HIGHLIGHT_OVERLAY_OPACITY = 0.5  # modo Translucido: se ve sobre fondos oscuros, el texto pierde algo de contraste

MARKER_STROKE = 5.0
DEFAULT_LENS_CORNER = 0.12   # esquinas del lente rectangular, como fraccion del lado menor
DEFAULT_LENS_FRAME_WIDTH = 4.0   # grosor del marco del lente (a escala 1); el origen y el conector llevan la mitad
MIN_LENS_FRAME_WIDTH = 1.0
MAX_LENS_FRAME_WIDTH = 20.0
MARKER_RX = 6.0
ARROW_LENGTH = 72.0
ARROW_GAP = 6.0
ARROW_HEAD = 13.0
ARROW_GLOW_OPACITY = 0.30
ARROW_GLOW_EXTRA = 8.0

STEP_RADIUS = 20.0
STEP_STROKE = 2.5
STEP_FONT_SIZE = 17.0

TEXT_LINE_HEIGHT = 1.25

# Presets de etiqueta de texto. Las claves son campos de TextLabel.
TEXT_PRESETS: dict[str, dict] = {
    "nota": {
        "color": CREAM, "bg": CARD_FILL, "border": TAN, "outline": None,
    },
    "exito": {
        "color": CREAM, "bg": SUCCESS_FILL, "border": SUCCESS_GREEN, "outline": None,
    },
    "alerta": {
        "color": CREAM, "bg": CARD_FILL, "border": RED, "border_width": 3.0, "outline": None,
    },
    "libre": {
        "color": CREAM, "bg": None, "border": None, "outline": PAGE_BG,
    },
}


def auto_scale(image_width: float) -> float:
    """Factor de escala de trazos segun el ancho de la imagen, acotado."""
    return min(MAX_SCALE, max(MIN_SCALE, image_width / REFERENCE_WIDTH))
