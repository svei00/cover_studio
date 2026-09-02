"""Modelo del documento de anotaciones. Todas las coordenadas estan en pixeles
de la imagen fuente."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from core.annotate.palette import BRAND_PALETTE, Palette
from core.annotate.style import (
    CARD_FILL,
    CREAM,
    DEFAULT_LENS_CORNER,
    DEFAULT_LENS_FRAME_WIDTH,
    HIGHLIGHT_MARKER_OPACITY,
    HIGHLIGHT_RADIUS,
    TAN,
    TEXT_PRESETS,
)


class ArrowSide(str, Enum):
    AUTO = "auto"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    NONE = "none"


class TextAlign(str, Enum):
    LEFT = "left"
    CENTER = "center"


class HighlightMode(str, Enum):
    MARKER = "marker"     # multiplica el color con lo de abajo: el texto negro sigue negro (fondos claros)
    OVERLAY = "overlay"   # color translucido normal: tambien se ve sobre fondos oscuros


class LensShape(str, Enum):
    CIRCLE = "circle"      # circulo (el origen se toma cuadrado)
    ELLIPSE = "ellipse"    # ovalo con las proporciones del rectangulo arrastrado
    ROUNDED = "rounded"    # rectangular; las esquinas se ajustan con `corner`


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def inflate(self, margin: float) -> Rect:
        return Rect(self.x - margin, self.y - margin, self.w + 2 * margin, self.h + 2 * margin)

    def intersects(self, other: Rect) -> bool:
        return not (
            self.right <= other.x or other.right <= self.x
            or self.bottom <= other.y or other.bottom <= self.y
        )


@dataclass(frozen=True)
class Marker:
    """Recuadro rojo con resplandor dorado y flecha."""

    id: str
    rect: Rect
    arrow: ArrowSide = ArrowSide.AUTO
    glow: bool = True
    # colores propios; None = el de la paleta del documento
    stroke_color: str | None = None
    glow_color: str | None = None
    arrow_color: str | None = None


@dataclass(frozen=True)
class Arrow:
    """Flecha suelta: apunta de start a end."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    glow: bool = True
    color: str | None = None
    glow_color: str | None = None


@dataclass(frozen=True)
class StepBadge:
    """Circulo numerado dorado, el de los pasos de las infografias."""

    id: str
    center: tuple[float, float]
    number: int
    color: str | None = None


@dataclass(frozen=True)
class TextLabel:
    """Etiqueta de texto. pos es la esquina superior izquierda de la caja.
    Con bg=None y outline definido el texto va suelto, con contorno para que
    se lea sobre cualquier captura."""

    id: str
    pos: tuple[float, float]
    text: str
    size: float = 28.0
    color: str = CREAM
    bold: bool = True
    bg: str | None = CARD_FILL
    bg_opacity: float = 0.92
    border: str | None = TAN
    border_width: float = 2.5
    padding: float = 12.0
    rx: float = 8.0
    align: TextAlign = TextAlign.LEFT
    outline: str | None = None


@dataclass(frozen=True)
class Redaction:
    """Zona pixelada para anonimizar. Se aplica al bitmap, no al SVG."""

    id: str
    rect: Rect
    block: int = 12


@dataclass(frozen=True)
class Magnifier:
    """Lupa: amplia `source` (region de la imagen) en un lente aparte centrado en
    `lens_center`. El tamano del lente es el del origen por `zoom`; con forma
    circular el origen se toma como el cuadrado centrado de lado max(w, h)."""

    id: str
    source: Rect
    lens_center: tuple[float, float]
    zoom: float = 2.0
    shape: LensShape = LensShape.CIRCLE
    connector: bool = True
    frame_color: str | None = None
    corner: float = DEFAULT_LENS_CORNER   # solo ROUNDED: 0 = esquinas rectas, 0.5 = muy redondeadas
    frame_width: float = DEFAULT_LENS_FRAME_WIDTH   # grosor del marco; el origen y el conector llevan la mitad
    glow: bool = False                    # resplandor alrededor del lente, como el del marcador
    glow_color: str | None = None         # None = el de la paleta


@dataclass(frozen=True)
class Highlight:
    """Resaltador: relleno de color sobre una zona (texto, celdas). `color` None = el de la
    paleta. `opacity` es la intensidad: en modo MARKER 1.0 es el color puro; en OVERLAY
    conviene ~0.5."""

    id: str
    rect: Rect
    color: str | None = None
    mode: HighlightMode = HighlightMode.MARKER
    opacity: float = HIGHLIGHT_MARKER_OPACITY
    radius: float = HIGHLIGHT_RADIUS


Annotation = Marker | Arrow | StepBadge | TextLabel | Redaction | Magnifier | Highlight


@dataclass
class AnnotationDoc:
    image_path: Path
    image_size: tuple[int, int]
    items: list[Annotation] = field(default_factory=list)
    style_scale: float | None = None
    padding: int = 0
    palette: Palette = BRAND_PALETTE
    crop: Rect | None = None   # region visible de la imagen fuente; None = la imagen completa

    @property
    def view(self) -> Rect:
        """Region de la imagen fuente que se muestra y se exporta (el recorte, o todo)."""
        if self.crop is not None:
            return self.crop
        return Rect(0.0, 0.0, float(self.image_size[0]), float(self.image_size[1]))


def text_label_from_preset(id: str, pos: tuple[float, float], text: str, preset: str = "nota") -> TextLabel:
    """Crea una TextLabel aplicando uno de TEXT_PRESETS."""
    if preset not in TEXT_PRESETS:
        raise ValueError(f"Preset de texto desconocido: {preset}")
    return replace(TextLabel(id=id, pos=pos, text=text), **TEXT_PRESETS[preset])
