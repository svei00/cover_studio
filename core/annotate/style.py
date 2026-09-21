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
CONNECTOR_GLOW_STRENGTH = 0.45   # el halo del conector apila 9 lineas llenas: cada una va a esta fraccion de la opacidad del anillo
# Ajuste del resplandor por anotacion: intensidad (multiplica la opacidad) y grosor (multiplica el alcance). 1.0 = el de siempre.
DEFAULT_GLOW_STRENGTH = 1.0
MIN_GLOW_STRENGTH = 0.1
MAX_GLOW_STRENGTH = 2.0
DEFAULT_GLOW_SIZE = 1.0
MIN_GLOW_SIZE = 0.3
MAX_GLOW_SIZE = 3.0


def glow_rings(strength: float = DEFAULT_GLOW_STRENGTH, size: float = DEFAULT_GLOW_SIZE) -> tuple[tuple[float, float], ...]:
    """Los anillos del resplandor con la intensidad y el grosor de la anotacion. UNA sola fuente de verdad: lo que se
    dibuja y lo que se calcula (cotas, margen) salen de aqui. Con los valores por defecto devuelve GLOW_RINGS tal cual."""
    return tuple((off * size, min(1.0, op * strength)) for off, op in GLOW_RINGS)


def glow_ring_width(size: float = DEFAULT_GLOW_SIZE) -> float:
    """Ancho de cada anillo. Crece con el grosor del halo para que los anillos sigan pegados (si no, con un halo
    ancho se ven nueve lineas sueltas); con un halo mas chico se queda como siempre."""
    return GLOW_RING_WIDTH * max(1.0, size)


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
MIN_LINE_WIDTH = 1.0
MAX_LINE_WIDTH = 24.0
DEFAULT_LENS_CORNER = 0.12   # esquinas del lente rectangular, como fraccion del lado menor
DEFAULT_LENS_FRAME_WIDTH = 4.0   # grosor del marco del lente (a escala 1); el origen y el conector llevan la mitad
MIN_LENS_FRAME_WIDTH = 1.0
MAX_LENS_FRAME_WIDTH = 20.0
MIN_LENS_PART_WIDTH = 0.5    # grosor propio del origen o del conector
MAX_LENS_PART_WIDTH = 20.0
MARKER_RX = 6.0
ARROW_LENGTH = 72.0
ARROW_GAP = 6.0
ARROW_HEAD = 13.0
ARROW_GLOW_OPACITY = 0.30
ARROW_GLOW_EXTRA = 8.0

# Lapiz y resaltador a mano alzada
PEN_WIDTH = 4.0
PEN_MARKER_WIDTH = 22.0
MIN_PEN_WIDTH = 1.0
MAX_PEN_WIDTH = 80.0

# Foco: lo de FUERA de la zona se oscurece y/o se desenfoca (se aplica al bitmap, no es una primitiva)
FOCUS_DIM = 0.55          # opacidad del oscurecido por defecto
MAX_FOCUS_DIM = 0.95
MAX_FOCUS_BLUR = 60.0     # radio maximo del desenfoque, en px de la captura
MAX_FOCUS_CORNER = 200.0

STEP_RADIUS = 20.0
STEP_STROKE = 2.5
STEP_FONT_SIZE = 17.0
STEP_NUMBER_RATIO = STEP_FONT_SIZE / STEP_RADIUS   # tamano automatico del numero respecto al paso
STEP_DIAMOND_FACTOR = 1.25      # semidiagonal del rombo / radio: misma area que el circulo
STEP_ROUNDED_CORNER = 0.4       # esquinas del cuadrado redondeado, como fraccion del radio
MIN_STEP_SIZE = 8.0
MAX_STEP_SIZE = 80.0
MIN_STEP_STROKE = 0.5
MAX_STEP_STROKE = 12.0
MIN_NUMBER_SIZE = 6.0
MAX_NUMBER_SIZE = 120.0

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
    # Alerta 2: la misma forma que Alerta, en el rojo de siempre (fondo, borde y letra blanca)
    "alerta2": {
        "color": "#FFFFFF", "bg": "#D32F2F", "border": "#8E1B1B", "border_width": 3.0, "outline": None,
    },
    # Nota 2: la misma forma que Nota, con el color de una nota post-it
    "nota2": {
        "color": "#333333", "bg": "#FFF3A3", "border": "#E0C84A", "outline": None,
    },
    "libre": {
        "color": CREAM, "bg": None, "border": None, "outline": PAGE_BG,
    },
}


def auto_scale(image_width: float) -> float:
    """Factor de escala de trazos segun el ancho de la imagen, acotado."""
    return min(MAX_SCALE, max(MIN_SCALE, image_width / REFERENCE_WIDTH))
