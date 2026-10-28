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
    ICON_RADIUS,
    DEFAULT_GLOW_SIZE,
    DEFAULT_GLOW_STRENGTH,
    DEFAULT_LENS_CORNER,
    DEFAULT_LENS_FRAME_WIDTH,
    HIGHLIGHT_MARKER_OPACITY,
    HIGHLIGHT_RADIUS,
    MARKER_STROKE,
    PEN_WIDTH,
    STEP_RADIUS,
    STEP_STROKE,
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


class LineStyle(str, Enum):
    SOLID = "solid"          # continua
    DASHED = "dashed"        # de rayas
    DOTTED = "dotted"        # de puntos
    DASH_DOT = "dash-dot"    # raya y punto


class HeadStyle(str, Enum):
    NONE = "none"
    ARROW = "arrow"
    DOT = "dot"


class PenMode(str, Enum):
    PEN = "pen"           # lapiz: trazo opaco
    MARKER = "marker"     # resaltador: multiplica con lo de abajo, el texto negro sigue negro (fondos claros)
    OVERLAY = "overlay"   # resaltador translucido: color normal con transparencia, se ve en fondos oscuros


class StepShape(str, Enum):
    CIRCLE = "circle"
    SQUARE = "square"
    ROUNDED = "rounded"   # cuadrado de esquinas redondeadas
    DIAMOND = "diamond"


class HighlightMode(str, Enum):
    MARKER = "marker"     # multiplica el color con lo de abajo: el texto negro sigue negro (fondos claros)
    OVERLAY = "overlay"   # color translucido normal: tambien se ve sobre fondos oscuros


class LensShape(str, Enum):
    CIRCLE = "circle"      # circulo (el origen se toma cuadrado)
    ELLIPSE = "ellipse"    # ovalo con las proporciones del rectangulo arrastrado
    ROUNDED = "rounded"    # rectangular; las esquinas se ajustan con `corner`


class IconKind(str, Enum):
    CHECK = "check"
    CROSS = "cross"
    WARNING = "warning"
    INFO = "info"
    QUESTION = "question"
    STAR = "star"
    PLUS = "plus"
    MINUS = "minus"


class IconStyle(str, Enum):
    SEAL = "seal"        # sello: contenedor relleno con el simbolo claro
    OUTLINE = "outline"  # contorno: contenedor blanco con borde y simbolo de color
    SYMBOL = "symbol"    # solo el simbolo, con un halo blanco para que se lea


class ConnectorRoute(str, Enum):
    STRAIGHT = "straight"   # una recta entre los dos extremos
    ELBOW = "elbow"         # tramos horizontales y verticales (con uno o dos codos en angulo recto)


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
    # flecha movida a mano: inicio (cola) y punta, en pixeles de la imagen. Van juntos; None = la
    # flecha automatica del lado elegido en `arrow`.
    arrow_start: tuple[float, float] | None = None
    arrow_tip: tuple[float, float] | None = None
    glow_strength: float = DEFAULT_GLOW_STRENGTH   # intensidad del resplandor (1.0 = el de siempre)
    glow_size: float = DEFAULT_GLOW_SIZE           # alcance del halo (1.0 = el de siempre)

    @property
    def custom_arrow(self) -> bool:
        return self.arrow_start is not None and self.arrow_tip is not None


@dataclass(frozen=True)
class Arrow:
    """Flecha suelta: de start a end, con punta al final. Con head_end=NONE y head_start=NONE es una
    LINEA (la herramienta Linea la crea asi), util de conector. `width` es el grosor a escala 1."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    glow: bool = True
    color: str | None = None
    glow_color: str | None = None
    head_start: HeadStyle = HeadStyle.NONE
    head_end: HeadStyle = HeadStyle.ARROW
    line_style: LineStyle = LineStyle.SOLID
    width: float = MARKER_STROKE
    glow_strength: float = DEFAULT_GLOW_STRENGTH
    glow_size: float = DEFAULT_GLOW_SIZE
    route: ConnectorRoute = ConnectorRoute.STRAIGHT   # ELBOW: un codo en angulo recto entre start y end
    elbow_vertical_first: bool = False                # en codo, sale en vertical (si no, en horizontal)


@dataclass(frozen=True)
class StepBadge:
    """Paso numerado, por defecto el circulo dorado de las infografias. `color` es el del borde
    y, si `number_color` es None, tambien el del numero. Los colores None usan el de la paleta
    (borde y numero) o el de marca (relleno)."""

    id: str
    center: tuple[float, float]
    number: int
    color: str | None = None
    shape: StepShape = StepShape.CIRCLE
    fill_color: str | None = None
    number_color: str | None = None
    size: float = STEP_RADIUS                 # radio (mitad del lado), a escala 1
    number_size: float | None = None          # None = automatico (proporcional a `size`)
    border_width: float = STEP_STROKE
    glow: bool = False
    glow_color: str | None = None
    glow_strength: float = DEFAULT_GLOW_STRENGTH
    glow_size: float = DEFAULT_GLOW_SIZE


@dataclass(frozen=True)
class Icon:
    """Icono vectorial (check, cruz, alerta, info, pregunta, estrella, mas, menos). `color` None = el de fabrica del
    icono (verde para el check, rojo para la cruz...); `glyph_color` None = automatico (claro sobre el sello, del color
    del icono en los otros estilos). `size` es el radio a escala 1. `ring` = borde blanco fino para que se vea sobre
    cualquier captura."""

    id: str
    center: tuple[float, float]
    kind: IconKind = IconKind.CHECK
    style: IconStyle = IconStyle.SEAL
    color: str | None = None
    glyph_color: str | None = None
    size: float = ICON_RADIUS
    ring: bool = True
    glow: bool = False
    glow_color: str | None = None
    glow_strength: float = DEFAULT_GLOW_STRENGTH
    glow_size: float = DEFAULT_GLOW_SIZE


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
    opacity: float = 1.0   # de toda la etiqueta (letra, fondo y borde); el fondo ademas lleva su bg_opacity


@dataclass(frozen=True)
class Redaction:
    """Zona pixelada para anonimizar. Se aplica al bitmap, no al SVG."""

    id: str
    rect: Rect
    block: int = 12


@dataclass(frozen=True)
class Spotlight:
    """Foco: la zona `rect` queda tal cual y TODO lo demas se oscurece (`dim`, 0..1) y/o se desenfoca (`blur`, radio
    en px). Se aplica al bitmap, despues del pixelado y de los recortes de las lupas, y por debajo de las anotaciones.
    Solo cuenta uno por documento (el ultimo). El desenfoque NO oculta datos: para eso esta el pixelado."""

    id: str
    rect: Rect
    dim: float = 0.55
    blur: float = 0.0
    corner: float = 0.0   # esquinas redondeadas de la zona, en px


@dataclass(frozen=True)
class ImageOverlay:
    """Imagen pegada encima de la captura (Ctrl+Shift+V): p. ej. el recorte de un menu que ya no se ve al abrir otro. Se
    compone en el BITMAP, antes del pixelado, de las lupas y del foco: asi Pixelar tambien anonimiza lo pegado y las
    anotaciones quedan por encima. `path` es el archivo guardado (el proyecto lo referencia); `size` su tamano ORIGINAL
    (para la proporcion y para "Tamano real"); `rect` donde va, en pixeles de la captura. Se remuestrea siempre desde el
    original. La sombra imita la flotante de Windows 11."""

    id: str
    path: str
    size: tuple[int, int]
    rect: Rect
    opacity: float = 1.0
    corner: float = 0.0            # esquinas redondeadas, en px de la captura
    shadow: bool = False
    shadow_strength: float = 1.0   # multiplica la opacidad de la sombra
    border: bool = False           # borde fino gris


@dataclass(frozen=True)
class Magnifier:
    """Lupa: amplia `source` (region de la imagen) en un lente aparte centrado en
    `lens_center`. El tamano del lente es el del origen por `zoom`; con forma
    circular el origen se toma como el cuadrado centrado de lado max(w, h)."""

    id: str
    source: Rect
    lens_center: tuple[float, float]
    zoom: float = 2.0
    shape: LensShape = LensShape.ROUNDED   # rectangular por defecto (la que mas se usa)
    connector: bool = True
    frame_color: str | None = None
    corner: float = DEFAULT_LENS_CORNER   # solo ROUNDED: 0 = esquinas rectas, 0.5 = muy redondeadas
    frame_width: float = DEFAULT_LENS_FRAME_WIDTH   # grosor del marco; el origen y el conector llevan la mitad
    glow: bool = False                    # resplandor alrededor del lente, como el del marcador
    glow_color: str | None = None         # None = el de la paleta
    # las tres partes de la lupa se pueden estilizar por separado. Color None = el del marco; grosor None =
    # la mitad del grosor del marco ("auto"). El estilo de siempre: marco continuo, origen de rayas, conector continuo.
    frame_style: LineStyle = LineStyle.SOLID
    source_color: str | None = None
    source_width: float | None = None
    source_style: LineStyle = LineStyle.DASHED
    connector_color: str | None = None
    connector_width: float | None = None
    connector_style: LineStyle = LineStyle.SOLID
    connector_glow: bool = False          # resplandor del conector (su color es `glow_color`, el del lente)
    glow_strength: float = DEFAULT_GLOW_STRENGTH   # intensidad y alcance del resplandor del lente Y del conector
    glow_size: float = DEFAULT_GLOW_SIZE
    # extremos del conector puestos a mano: posicion (u, v) en el borde de la caja del origen / del lente, como
    # fraccion de esa caja (0..1), para que sigan a la lupa al moverla, redimensionarla o cambiar el zoom.
    # None = el automatico.
    connector_start: tuple[float, float] | None = None
    connector_end: tuple[float, float] | None = None
    connector_route: ConnectorRoute = ConnectorRoute.STRAIGHT

    @property
    def custom_connector(self) -> bool:
        return self.connector_start is not None or self.connector_end is not None


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


@dataclass(frozen=True)
class Stroke:
    """Trazo a mano alzada (lapiz o resaltador). `points` son los puntos de CONTROL ya suavizados y simplificados
    (core.annotate.freehand); al dibujar se unen con una curva. Color None = el de la paleta (lapiz) o el del
    resaltador. `opacity` es de todo el trazo."""

    id: str
    points: tuple[tuple[float, float], ...]
    color: str | None = None
    mode: PenMode = PenMode.PEN
    width: float = PEN_WIDTH            # grosor a escala 1
    opacity: float = 1.0
    glow: bool = False
    glow_color: str | None = None
    glow_strength: float = DEFAULT_GLOW_STRENGTH
    glow_size: float = DEFAULT_GLOW_SIZE


Annotation = Marker | Arrow | StepBadge | Icon | TextLabel | Redaction | Magnifier | Highlight | Stroke | Spotlight | ImageOverlay


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
