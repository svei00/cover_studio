"""Modelo del documento de anotaciones. Todas las coordenadas estan en pixeles
de la imagen fuente."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from core.annotate.style import CARD_FILL, CREAM, TAN, TEXT_PRESETS


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


@dataclass(frozen=True)
class Arrow:
    """Flecha suelta: apunta de start a end."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    glow: bool = True


@dataclass(frozen=True)
class StepBadge:
    """Circulo numerado dorado, el de los pasos de las infografias."""

    id: str
    center: tuple[float, float]
    number: int


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


Annotation = Marker | Arrow | StepBadge | TextLabel | Redaction


@dataclass
class AnnotationDoc:
    image_path: Path
    image_size: tuple[int, int]
    items: list[Annotation] = field(default_factory=list)
    style_scale: float | None = None
    padding: int = 0


def text_label_from_preset(id: str, pos: tuple[float, float], text: str, preset: str = "nota") -> TextLabel:
    """Crea una TextLabel aplicando uno de TEXT_PRESETS."""
    if preset not in TEXT_PRESETS:
        raise ValueError(f"Preset de texto desconocido: {preset}")
    return replace(TextLabel(id=id, pos=pos, text=text), **TEXT_PRESETS[preset])
