# Arquitectura — pestaña "Anotar"

Editor de capturas dentro de Cover Studio: marcador con resplandor, flechas,
pasos numerados, pixelado para anonimizar y lupa. Mantiene la identidad visual
de `excel-solutions-social` (`infographic_builder.py`).

Estado: diseño aprobado pendiente. Nada implementado.

---

## 1. Decisiones

| Decisión | Por qué |
|---|---|
| Pestaña dentro de Cover Studio, no otra app | Reusa PySide6, resvg, drag&drop, guarda de sobrescritura y presets. |
| Captura de pantalla fuera de alcance | Lightshot / `Win + Shift + S` ya lo hacen. La pestaña acepta `CTRL + V`, arrastrar y Examinar. |
| **Una sola geometría, dos rasterizadores** | `core` produce una lista de primitivas (rect, línea, polígono, círculo, imagen recortada). La UI las pinta con `QPainter` para editar a 60 fps; el export las convierte a SVG y las rasteriza con resvg. La geometría nunca se duplica; solo puede variar el antialiasing. |
| No se renderiza con resvg mientras se edita | Medido en este proyecto: 180–640 ms por render a 1080p. Inservible para arrastrar. |
| Coordenadas siempre en píxeles de la imagen fuente | Mismo patrón que `PreviewWidget._widget_to_canvas`. Evita la clase de bugs de escala. |
| Pixelado antes que todo lo demás | Se aplica al bitmap base con Pillow. La lupa y el export SVG usan ese bitmap ya pixelado, así que **un dato anonimizado nunca reaparece dentro de una lupa ni en el SVG**. |
| Sin herramienta de texto libre | Tu skill pone las etiquetas como `<text>` del SVG de la infografía. Texto quemado en el bitmap no lo ve `check_collisions.py` y no es accesible. Los números de paso sí van. |
| Proyecto re-editable | Las anotaciones se guardan como JSON junto a la captura (`captura.anotar.json`). Si encuentras un error después de exportar, reabres y corriges, no redibujas. |

---

## 2. Identidad visual (valores copiados de `infographic_builder.py`)

Se copian como constantes en `core/annotate/style.py` con un comentario que
cite la fuente. No se importa el builder: vive en AppData y su ruta cambia.

| Elemento | Valor |
|---|---|
| Resplandor | `#E8B95C`, anillos `GLOW = ((i*2.2, round(0.55*(1-i/10)**1.6, 4)) for i in 1..9)`, `stroke-width 4.5`, `rx = rx + off` |
| Recuadro | `#621132`, `sw = 5`, `rx = 6` |
| Flecha | largo 72, separación 6 del recuadro, punta `head = 13` (1.3 × 0.8), glow de la flecha `sw + 8` a opacidad 0.30 |
| Paso numerado | círculo r=20, borde `#B38E5D` sw 2.5, número `#B38E5D` bold 17 |
| Marco de lupa | `#D4C19C` (tan = marcos, según la paleta) |

**Ajuste necesario para capturas** (no existe en el builder porque ahí el
círculo va sobre fondo navy): el paso numerado lleva relleno `#1B3350` (card
fill). Un círculo solo con borde dorado se pierde sobre una captura clara.

**Escala de marca.** El builder dibuja sobre un lienzo de ~1600 px. Una captura
de 4K con un trazo de 5 px se ve fino una vez reducida en la infografía. Todos
los grosores, radios y largos se multiplican por
`style_scale = image_width / 1600` (automático, editable con un slider).

---

## 3. Lupa

Amplía una región y la muestra en un lente aparte, unido a la región de origen.

```
modelo:  source (rect en px de imagen) · lens_center · lens_size · zoom · shape (circle|rounded) · connector (bool)
render:  Pillow recorta `source` del bitmap YA pixelado, lo amplía con LANCZOS al tamaño del lente
         y ese recorte se incrusta como imagen propia, recortada con clipPath.
marco:   tan #D4C19C, 4 px × style_scale; contorno discontinuo tan sobre la región de origen;
         conector: dos líneas tangentes (círculo) o una línea recta entre bordes (rounded).
```

Reglas:
- **Zoom recomendado 1.5x–2.5x.** Arriba de ~2.5x el texto de un bitmap se ve borroso; ningún algoritmo inventa detalle. La UI avisa arriba de 3x.
- El lente nunca tapa su propia región de origen; se coloca automáticamente en el lado con más espacio y luego se arrastra.
- Para texto que realmente necesita ser legible en un teléfono, lo correcto sigue siendo capturar con más zoom en Excel. La lupa es para señalar un detalle dentro de una captura amplia, no para rescatar una captura mala. Esto va en el tooltip.

Se amplía con Pillow y no con un `transform scale` dentro del SVG porque así
se controla el filtro (LANCZOS) y el resultado es igual en el editor y en el
export.

---

## 4. Archivos

```
core/annotate/
  __init__.py
  style.py        constantes de marca + style_scale
  model.py        dataclasses del documento de anotaciones
  primitives.py   modelo -> lista de primitivas (aquí vive el port de marker())
  raster.py       Pillow: carga, pixelado, recorte de lupa
  svg.py          primitivas -> SVG; reusa render_png_bytes de core/geometry.py
  io.py           guardar/cargar el JSON sidecar (mismo patrón que presets.py)

ui/annotate/
  __init__.py
  tab.py          AnnotateTab: barra de herramientas + lienzo + panel de propiedades
  canvas.py       QGraphicsView/QGraphicsScene, selección y manijas
  painter.py      pinta primitivas con QPainter
  commands.py     QUndoCommand para crear/mover/redimensionar/borrar

ui/main_window.py  el widget central pasa a QTabWidget: "Portada" | "Anotar"

tests/
  test_annotate_primitives.py  test_annotate_raster.py
  test_annotate_svg.py         test_annotate_io.py
```

---

## 5. Firmas principales

```python
# core/annotate/model.py
class ArrowSide(str, Enum):  AUTO="auto"; LEFT="left"; RIGHT="right"; TOP="top"; BOTTOM="bottom"; NONE="none"
class LensShape(str, Enum):  CIRCLE="circle"; ROUNDED="rounded"

@dataclass(frozen=True)
class Rect:  x: float; y: float; w: float; h: float

@dataclass(frozen=True)
class Marker:     id: str; rect: Rect; arrow: ArrowSide = ArrowSide.AUTO; glow: bool = True
@dataclass(frozen=True)
class Arrow:      id: str; start: tuple[float, float]; end: tuple[float, float]; glow: bool = True
@dataclass(frozen=True)
class StepBadge:  id: str; center: tuple[float, float]; number: int
@dataclass(frozen=True)
class Redaction:  id: str; rect: Rect; block: int = 12
@dataclass(frozen=True)
class Magnifier:  id: str; source: Rect; lens_center: tuple[float, float]; lens_size: float
                  zoom: float = 2.0; shape: LensShape = LensShape.CIRCLE; connector: bool = True

Annotation = Marker | Arrow | StepBadge | Redaction | Magnifier

@dataclass
class AnnotationDoc:
    image_path: Path
    image_size: tuple[int, int]
    items: list[Annotation]            # orden de dibujo; las Redaction se aplican primero siempre
    style_scale: float | None = None   # None = automático (ancho / 1600)
    padding: int = 0                   # margen extra relleno #1B3350 para que el glow no se corte

# core/annotate/primitives.py
@dataclass(frozen=True)
class PRect:    rect: Rect; stroke: str; width: float; opacity: float; rx: float; fill: str | None = None
@dataclass(frozen=True)
class PLine:    a: tuple[float, float]; b: tuple[float, float]; stroke: str; width: float; opacity: float; dash: str | None = None
@dataclass(frozen=True)
class PPolygon: points: tuple[tuple[float, float], ...]; fill: str | None; stroke: str | None; width: float; opacity: float
@dataclass(frozen=True)
class PCircle:  center: tuple[float, float]; r: float; fill: str | None; stroke: str; width: float
@dataclass(frozen=True)
class PText:    pos: tuple[float, float]; text: str; size: float; color: str; bold: bool
@dataclass(frozen=True)
class PImage:   key: str; dest: Rect; clip: LensShape     # key -> imagen recortada por raster.py

Primitive = PRect | PLine | PPolygon | PCircle | PText | PImage

def resolve_arrow_side(marker: Marker, image_size, others: Sequence[Annotation], scale: float) -> ArrowSide:
    """AUTO -> el lado con más espacio libre dentro de la imagen y sin pasar sobre otras anotaciones."""
def marker_primitives(m: Marker, scale: float, side: ArrowSide) -> list[Primitive]:
    """Port 1:1 de Doc.marker(): anillos de glow, recuadro, línea + punta con su glow."""
def arrow_primitives(a: Arrow, scale: float) -> list[Primitive]: ...
def step_primitives(s: StepBadge, scale: float) -> list[Primitive]: ...
def magnifier_primitives(g: Magnifier, scale: float) -> list[Primitive]: ...
def build_primitives(doc: AnnotationDoc) -> list[Primitive]:
    """Las Redaction no producen primitivas: viven en el bitmap."""

# core/annotate/raster.py
def load_image(path: Path) -> Image.Image:                 # exif_transpose + RGBA
def apply_redactions(img: Image.Image, items: Sequence[Annotation]) -> Image.Image:
    """Pixelado irreversible: reduce el bloque con BOX y lo regresa con NEAREST."""
def lens_crops(img: Image.Image, items: Sequence[Annotation]) -> dict[str, Image.Image]:
    """Un recorte LANCZOS por lupa, tomado del bitmap ya pixelado."""

# core/annotate/svg.py
def to_svg(doc: AnnotationDoc, base: Image.Image, crops: dict[str, Image.Image],
           primitives: Sequence[Primitive]) -> str: ...
def export_png(doc: AnnotationDoc, output_path: Path) -> None:
    """load -> apply_redactions -> lens_crops -> build_primitives -> to_svg -> render_png_bytes."""

# core/annotate/io.py
def sidecar_path(image_path: Path) -> Path:                # captura.png -> captura.anotar.json
def save_doc(doc: AnnotationDoc, path: Path) -> None: ...
def load_doc(path: Path) -> AnnotationDoc: ...
```

---

## 6. Tests que no son opcionales

- **Port fiel de `marker()`:** para `marker(100, 100, 200, 50, arrow="left")` con `scale=1`, las coordenadas de la línea y de la punta coinciden con las que produce el builder (valores calculados a mano y fijados en el test).
- **El dato pixelado no se filtra:** después de `export_png` con una `Redaction`, el SVG intermedio no contiene el base64 del archivo original, y los píxeles dentro de una lupa que cubre la zona pixelada salen pixelados.
- Pixelado: dentro de cada bloque todos los píxeles son iguales.
- Lupa: el recorte mide `lens_size` y el lente no se superpone a su `source`.
- `resolve_arrow_side`: un marcador pegado al borde izquierdo nunca recibe flecha izquierda.
- Ida y vuelta del JSON sidecar.

---

## 7. Exportar

- Salida por defecto: `<nombre>-anotada.png` junto a la captura. **El original nunca se sobrescribe por defecto**; si el usuario elige la misma ruta, se reusa el diálogo `SOBRESCRIBIR` de la pestaña Portada.
- Opcional: SVG (con el bitmap ya pixelado incrustado) y copiar al portapapeles.
- Aviso si un marcador queda a menos de 20 px × `style_scale` del borde: el glow se recorta. Ofrecer `padding`.

---

## 8. Fases (cada una cabe en una sesión corta)

1. `style.py`, `model.py`, `primitives.py` (marcador, flecha, paso) + tests. Sin UI.
2. `raster.py`, `svg.py`, `io.py` + tests. Al terminar ya se puede anotar desde un JSON sin abrir ventana.
3. Pestaña: `QTabWidget`, cargar/pegar/arrastrar, mostrar la captura con sus anotaciones, botón Exportar.
4. Herramientas interactivas: crear, seleccionar, mover, redimensionar, borrar, deshacer.
5. Lupa interactiva + colocación automática del lente.
6. Pulido: reabrir desde el sidecar, copiar al portapapeles, padding.

## Para después (fuera de este alcance)

Exportar las anotaciones como datos para que `infographic_builder.py` dibuje los
marcadores como vectores en la infografía, en vez de quemados en el PNG. Así
`check_collisions.py` también los podría verificar.
