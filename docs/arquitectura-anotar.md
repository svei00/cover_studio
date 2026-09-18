# Arquitectura — pestaña "Anotar"

Editor de capturas dentro de Cover Studio: marcador con resplandor, flechas,
pasos numerados, pixelado para anonimizar y lupa. Mantiene la identidad visual
de `excel-solutions-social` (`infographic_builder.py`).

Estado: **las 6 fases hechas.**

Fase 6, pulido:
- Margen extra alrededor de la captura (`AnnotationDoc.padding`) y escala de trazo
  manual o automatica, ambos con deshacer (`_DocPropertyCommand`, que fusiona los
  cambios seguidos de la misma propiedad).
- `core/annotate/bounds.py`: `required_padding(doc)` calcula, a partir de lo realmente
  dibujado (resplandor, flechas, etiquetas), cuantos px de margen evitan el recorte.
  El panel avisa y ofrece "Agregar margen de N px"; al exportar tambien avisa.
- El lienzo recorta lo que se sale del area exportada (imagen + margen): la pantalla
  muestra lo mismo que saldra en el PNG.
- Guardar proyecto (CTRL + S), abrir `.anotar.json` desde "Abrir...", Copiar al
  portapapeles (CTRL + C, `render_bytes`).
- Estado "sin guardar" = `not QUndoStack.isClean()`: volver con deshacer al estado
  guardado lo deja limpio. Confirma antes de abrir otra captura o cerrar la ventana;
  la pestaña muestra un asterisco.
- 283 pruebas en total. `tests/conftest.py` descarta por defecto el dialogo de cambios
  sin guardar (es modal: sin esto una prueba se queda esperando para siempre).

Fase 5, la lupa (resumen original):

Fase 5, la lupa (`Magnifier`):
- `core/annotate/lens.py` (puro): origen efectivo (circular = cuadrado de lado max(w,h)),
  lente = origen x zoom, conector (dos tangentes externas si es circular; una recta
  entre bordes si es rectangular), colocación automática (`default_lens_center`) y
  `is_crowded`.
- El recorte sale del bitmap YA pixelado (`raster.lens_crops`): un dato anonimizado
  no reaparece dentro de una lupa ni en el SVG. En pantalla el recorte se cachea por
  (pixelados, origen, zoom, forma); mover el lente no lo recalcula.
- Edición: el lente y el origen se mueven por separado (cuerpo del lente vs borde del
  origen), un asa en la esquina del lente cambia el zoom, y las 8 asas del origen lo
  redimensionan. Cambiar zoom o forma recoloca el lente si queda encima o a menos de
  la mitad del hueco estándar de su origen. Botón "Recolocar lupa" en el panel.
- Zoom recomendado hasta 3x; arriba de eso el panel avisa que el texto se verá borroso.
- 242 pruebas en total.

Fase 4: edición interactiva.
- `core/annotate/edit.py` (puro): hit-testing, asas, mover y redimensionar.
- `ui/annotate/controller.py`: herramienta, selección, gestos y pila de deshacer/rehacer
  (`QUndoStack`). Los gestos modifican el documento en vivo y al soltar empujan UN
  comando idempotente; los cambios seguidos de propiedades y los empujones con
  flechas se fusionan en un solo paso.
- `ui/annotate/panel.py`: propiedades por tipo. `ui/annotate/canvas.py`: mouse,
  teclado (Suprimir, Esc, flechas, MAYÚS para 10 px), caja y asas de selección.
- Herramientas: Seleccionar, Marcador, Flecha, Paso, Texto, Pixelar. Cada una
  vuelve a Seleccionar tras dibujar. Un clic o arrastre minúsculo no crea nada.
- 163 + 16 pruebas de interacción con eventos de mouse y teclado reales.

(Lo de abajo describe las fases 1-3, ya implementadas.)
- `core/annotate/` (style, model, primitives, text_measure, errors, raster, svg, io).
- `ui/annotate/` (painter, canvas, tab) + `ui/dialogs.py`; `main_window.py` ahora
  es un `QTabWidget` "Portada" | "Anotar". La pestaña abre, pega (`CTRL + V`) y
  recibe arrastres; muestra la captura con sus anotaciones; exporta PNG/SVG con la
  guarda de sobrescritura. Aún no se puede crear anotaciones con el mouse.
- 69 tests de anotaciones. Los de UI corren con `QT_QPA_PLATFORM=offscreen`, que en
  Windows no tiene fuentes: el texto sale como cuadros en `grab()`. Para revisar a
  ojo, renderizar con la plataforma `windows` (la ventana no necesita verse).

Pendiente: herramientas interactivas (fase 4), lupa (`Magnifier`, fase 5), pulido (fase 6).

Decisión de la fase 3: al exportar SOBRE la captura original, se respalda como
`<nombre>.original.<ext>` y la pestaña sigue editando contra el respaldo (así el
proyecto `.anotar.json` nunca apunta a un archivo ya anotado).

Nota: en el código, `Magnifier` todavía no existe en el modelo; entra en la fase 5.
La firma `Annotation` hoy es `Marker | Arrow | StepBadge | TextLabel | Redaction`.

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
| **Etiqueta de texto (`TextLabel`)**, más potente que la de Lightshot | Multilínea, negrita, alineación, fondo con opacidad, borde, esquinas redondeadas, contorno para texto suelto, y 4 presets de marca (`nota`, `exito`, `alerta`, `libre`). Tradeoff conocido: el texto queda quemado en el PNG, así que `check_collisions.py` no lo ve y no es accesible. Por eso se recomienda dejar el texto largo para la infografía y usar la etiqueta para rótulos cortos. |
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

---

## Cambios posteriores

### Colores (paleta del documento + color propio por anotacion)

- `core/annotate/palette.py` (sin Qt): `Palette(marker, arrow, glow, lens, step)` con los
  colores de marca por defecto; `palette_to_dict` / `palette_from_dict` (un dato invalido o
  ausente cae al de marca SOLO en ese campo, asi un proyecto viejo se abre igual).
- Cada anotacion tiene campos de color opcionales (`Marker.stroke_color/glow_color/arrow_color`,
  `Arrow.color/glow_color`, `StepBadge.color`, `Magnifier.frame_color`); `None` = usa la paleta.
  Las primitivas reciben la paleta (`palette=BRAND_PALETTE` por defecto, asi nada existente cambio).
- El contorno navy que da contraste a los trazos de la lupa NO es configurable a proposito.
- Pendiente a futuro: guardar la paleta como preset (el modulo ya esta aparte, sin Qt, para eso),
  y selectores de color para las etiquetas de texto (hoy solo por presets).

### Granularidad del deshacer

Una decision es un paso. Los colores se eligen en un dialogo modal: cada uno es su propio paso
(`edit_selected(_merge=False, ...)`, `set_palette` sin fusion). Las ediciones de propiedades solo se
fusionan si son del MISMO campo (`_ReplaceCommand` guarda los campos editados): escribir texto o girar
un spinbox es un paso; cambiar forma y luego zoom son dos. `_merge` lleva guion bajo para no chocar
con campos de los dataclasses (un parametro llamado `text` ya causo ese bug).

### Lupa: forma ovalada y esquinas ajustables

- `LensShape.ELLIPSE`: el origen y el lente son ovalos con las proporciones del rectangulo arrastrado
  (el circulo, en cambio, cuadra el origen). Pasar de circular a ovalada conserva lo arrastrado.
- `Magnifier.corner` (0 a 0.5, por defecto 0.12 = el de siempre): esquinas del lente rectangular.
- Primitiva nueva `PEllipse` (pintor, SVG, bounds). Conector ovalado: recta entre los bordes sobre
  la linea de los centros. La seleccion de un ovalo ignora la esquina vacia de su caja.
- Un ovalo recorta el texto en sus puntas: para texto conviene la forma rectangular.


### Recorte no destructivo

- `AnnotationDoc.crop: Rect | None` (pixeles de la fuente, enteros) y `doc.view` = el recorte o la imagen
  completa. Las anotaciones NO se mueven: siguen en coordenadas de la fuente. `core/annotate/crop.py` (sin Qt)
  tiene `normalize_crop` (limita a la imagen, redondea, descarta lo menor a 16 px o lo que cubre todo),
  asas y `resize_crop`.
- Export (`svg.py`): lienzo = `view` + margen, contenido trasladado por `-crop`. Al SVG solo viaja el bitmap
  recortado (los pixeles de fuera no quedan en el archivo). Pixelados y lupas leen el bitmap COMPLETO.
- `doc_scale` automatico usa el ancho de la IMAGEN completa, no el del recorte: recortar es una ventana y las
  anotaciones se ven igual (decidido con Svei tras ver que con el ancho del recorte se adelgazaban).
- Margen: `required_padding` mide contra `view`; lo que queda del todo fuera del recorte no pide margen y
  `bounds.items_outside_view` lo cuenta para avisar en el panel. Colocacion automatica de flecha y lupa usan
  `view` como region.
- Herramienta Recortar (`Tool.CROP`): el lienzo muestra la imagen COMPLETA con lo de fuera oscurecido y 8 asas
  (sin recorte, las asas estan en las esquinas de la imagen). El gesto vive en `controller.crop_draft` y al
  soltar empuja UN `_DocPropertyCommand("crop")`. Un arrastre menor a 16 px no hace nada. `Esc` cancela.
- El JSON guarda `"crop": [x, y, w, h] | null`; sin la clave o con un valor invalido abre la captura completa.

### Lupa: grosor del borde y resplandor

- `Magnifier.frame_width` (4 por defecto, 1 a 20, a escala 1): grosor del marco del lente. El contorno navy
  vale `frame_width + 4`; el origen punteado y el conector llevan la mitad (`frame_width / 2`, contorno `+2`).
  Con el valor por defecto el dibujo es identico al de siempre.
- `Magnifier.glow` (apagado por defecto) y `glow_color` (None = paleta): los mismos 9 anillos del marcador,
  alrededor del lente y siguiendo su forma (circulo, ovalo, rectangulo). Van DEBAJO de todo (conector y origen
  encima; la imagen del lente tapa lo que cae dentro). El origen punteado no lleva resplandor.

### Restablecer al valor por defecto (panel)

- `PropertiesPanel._reset_row` / `_field_row`: doble clic en la etiqueta de un control (como en DaVinci
  Resolve) o el boton de restablecer lo devuelven a su valor de fabrica. El boton solo se activa si el valor
  ya no es el de fabrica (`_refresh_resets` al final de `sync`). Restablecer es SU PROPIO paso de deshacer,
  asi que se puede volver al valor anterior.
- Cubre: margen, escala de trazo, lado de flecha, tamano y alineacion del texto, bloque del pixelado, zoom,
  forma, esquinas y grosor de la lupa, y el modo, intensidad y esquinas del resaltador. Las etiquetas de
  color (de anotacion o de la paleta del documento) tambien: doble clic = color de la paleta / de marca.
- El valor de fabrica puede depender del contexto (bloque del pixelado = 12 x escala; intensidad del
  resaltador segun su modo): `_field_row` acepta una funcion como `default`.
- Los checkboxes (resplandor, conector, negrita) no tienen restablecer.

### Resaltador

- `Highlight(id, rect, color=None, mode, opacity, radius)`; `Palette.highlight` es el color por defecto
  (amarillo). `style.HIGHLIGHT_SWATCHES`: amarillo #FFF200, verde #7CFC00, rosa #FF69B4, naranja #FFA500, azul
  claro #00BFFF (revisados sobre fondo claro y oscuro).
- Dos modos, medidos con resvg y con el pintor de Qt (dan lo mismo):
  - MARKER: `mix-blend-mode: multiply` (`PRect.blend`; en Qt, `CompositionMode_Multiply`). El color sale
    puro y el texto negro sigue negro. Sobre fondo OSCURO casi no se ve (multiplicar por casi negro).
  - OVERLAY: color translucido normal (intensidad 50 %). Se ve sobre oscuro; el texto pierde algo de contraste.
  Cambiar de modo ajusta la intensidad (100 % / 50 %) en un solo paso de deshacer.
- Se dibuja en el orden de la lista como cualquier anotacion (no es del bitmap): las lupas muestran la imagen
  SIN resaltar. No cuenta como obstaculo para las flechas ni la lupa (`item_bounds` = None).
- `ui/widgets.py::ColorSwatchRow`: fila de muestras reutilizable (aun solo la usa el resaltador).

### Seleccion: interior y flecha del marcador

- Bug reportado por Svei ("seleccionar no funciona"): un clic DENTRO de un marcador o sobre su flecha no
  seleccionaba nada (solo respondia el borde del recuadro). Ahora `edit.hit_test` acepta `arrows` (id de
  marcador -> (inicio, punta), calculado por `primitives.marker_arrow` / `controller.marker_arrows()`) y hace
  dos pasadas: primero lo que esta bajo el punto (borde, flecha, y todo lo demas); si no hay nada, el
  interior de un marcador. Asi lo que esta DENTRO de un marcador (un paso, un texto) sigue seleccionable.

### Zoom y desplazamiento del lienzo (solo de vista)

- `AnnotateCanvas` guarda `_zoom` (None = "Ajustar", tope 2x como siempre) y `_center`: el PUNTO DE LA IMAGEN
  que queda en el centro de la ventana (no un offset en pixeles). Asi un cambio de tamano de la ventana, de
  margen o de recorte (la herramienta Recortar muestra la imagen completa) no mueve lo que se mira.
  `view_layout()` sigue siendo el unico lugar que convierte pantalla <-> imagen; hit-test, asas, tolerancia y
  seleccion lo heredan sin cambios.
- Rueda = zoom hacia el cursor (el punto bajo el cursor no se mueve; x1.2 por clic, tope 32x, nunca baja del
  ajuste y a menos de 1 % del ajuste vuelve al modo ajustado). Boton central o Espacio + arrastrar = mover
  (el touchpad horizontal tambien). `_clamp_center`: si la imagen cabe se centra; si no, su borde nunca se
  separa mas de 12 px del borde de la ventana (no se puede "perder" la imagen ni dejar huecos grandes).
- Barra bajo el lienzo: Ajustar (CTRL + 0), 100 % (CTRL + 1), etiqueta de zoom; CTRL + / CTRL - acercan y
  alejan. Con escala > 2x se pintan los pixeles sin suavizar, para ubicar con precision.
- Cambiar de captura reinicia la vista a "Ajustar". El export no depende del zoom (hay un test con hash).

### Flecha del marcador movible

- `Marker.arrow_start` / `arrow_tip` (opcionales, van juntos; `Marker.custom_arrow`): la flecha puesta a mano, en
  pixeles de la imagen. None = la flecha automatica del lado de `arrow`. `primitives.marker_arrow` devuelve los
  puntos ya resueltos (propios o automaticos) y es lo que usan el dibujo, la seleccion y las asas.
- Un marcador con flecha suma dos asas, START (cola) y END (punta), a sus 8 del recuadro; gana la mas cercana al
  mouse. Arrastrar una fija AMBOS extremos (el otro se queda donde estaba). Arrastrar el cuerpo de la flecha
  (`edit.hit_marker_part` = "arrow": mas cerca de ella que del borde del recuadro) mueve solo la flecha, incluso
  sin haber seleccionado el marcador antes. Mover el marcador por su borde arrastra tambien una flecha propia.
- Los puntos de las flechas se congelan al empezar el gesto (`controller._press_arrows`): durante el arrastre
  no se recalculan. Cada gesto es UN paso de deshacer.
- Elegir un lado en el panel pide la flecha AUTOMATICA de ese lado (suelta la propia); el boton de restablecer
  del lado y "Recolocar flecha" (solo visible con flecha propia) la devuelven a automatica.
- `"arrow_start"`/`"arrow_tip"` en el JSON; si falta o es invalido uno de los dos, ninguno cuenta.

### Herramientas que se quedan activas

- `controller.STICKY_TOOLS` = Marcador, Recuadro, Resaltar, Flecha, Paso, Pixelar y Lupa: tras dibujar, la
  anotacion nueva queda seleccionada (su panel visible y editable) y la herramienta SIGUE activa, para dibujar
  otra sin volver a elegirla. El texto no (abre su editor): vuelve a Seleccionar. Se sale con Esc (la ultima
  anotacion queda seleccionada; un segundo Esc deselecciona) o eligiendo otra herramienta.
- Con una herramienta activa, arrastrar sobre algo ya dibujado crea otra anotacion en vez de seleccionarlo: para
  mover o redimensionar se sale a Seleccionar. Esc a mitad de un gesto lo cancela y sale de la herramienta.
- Los tooltips de esas herramientas lo avisan. Los tests que dibujaban y luego editaban dan por hecho el cambio
  con `tab.tool_buttons[Tool.SELECT].click()` despues de dibujar.

### Paso numerado: forma, colores, tamano y resplandor

- `StepBadge` suma `shape` (`StepShape`: circulo, cuadrado, cuadrado redondeado, rombo), `fill_color`,
  `number_color`, `size` (radio a escala 1, 20), `number_size` (None = automatico, proporcional: 17/20 del
  radio), `border_width` (2.5), `glow` y `glow_color`. `color` sigue siendo el borde y, si `number_color` es None,
  tambien el numero. Con los valores por defecto el dibujo es identico al de siempre (hay un test que lo fija).
- El rombo usa semidiagonal = 1.25 x radio (misma area que el circulo); `primitives.step_extent` da el
  semi-ancho de cada forma y lo usan la seleccion, las cajas y `item_bounds`. El clic respeta la forma (circulo:
  distancia; cuadrados: caja; rombo: |dx| + |dy|).
- Resplandor: los 9 anillos del marcador siguiendo la forma (el del rombo se ensancha `o * raiz(2)`), debajo del
  paso. Panel: forma, tres colores (doble clic en la etiqueta = valor de fabrica), tamano, tamano del numero
  ("Auto" = 0), grosor y resplandor, todos con restablecer.
- No hay asas de tamano en el lienzo (solo el panel). Los pasos nuevos salen siempre con el estilo de fabrica.

### Linea / conector y estilos de linea

- No hay una anotacion nueva: `Arrow` suma `head_start`/`head_end` (`HeadStyle`: ninguna, flecha, punto),
  `line_style` (`LineStyle`: continua, de rayas, de puntos, raya y punto) y `width` (grosor a escala 1, 5 por
  defecto). La herramienta **Linea** crea una `Arrow` con `head_end=NONE` (una linea recta, util de conector); sin
  puntas en ningun extremo el panel la titula "Linea", si no "Flecha". Seleccion, asas, mover y deshacer son
  los de la flecha. Un dato invalido o ausente del JSON usa el de siempre (flecha con punta final, continua, 5).
- Infraestructura comun, tambien para la lupa: `primitives.dash_pattern(estilo, grosor)` devuelve (rayas, remate).
  Las rayas se miden en MULTIPLOS DEL GROSOR (de rayas 3w/2w, de puntos ~0/2w con remate redondo, raya-punto
  2w/2.5w/~0/2.5w), asi se ven proporcionadas con cualquier grosor. `PLine`, `PRect`, `PCircle` y `PEllipse`
  tienen `dash` (tupla de cualquier largo par) y `cap` ("butt" o "round"); el SVG escribe `stroke-dasharray` con
  3 decimales y `stroke-linecap`; el pintor de Qt usa `QPen.setDashPattern` (en multiplos del grosor) y
  `RoundCap`. Hay un test que MIDE que resvg y Qt dejan la misma proporcion de tinta por estilo.
- La punta sigue al grosor (x0.5 a x3 de la de 13 px) y el resplandor de una linea de rayas lleva las mismas rayas.
- `ui/flow_layout.py`: la barra de herramientas es un `FlowLayout` (baja a una segunda fila si no cabe). Con la
  herramienta nueva la fila sola obligaba a la ventana a medir 1704 px; ahora el minimo es ~1292 (lo fija la
  barra superior). La etiqueta de ayuda del zoom se recorta en ventanas estrechas.

### Lupa: marco, origen y conector independientes

- `Magnifier` suma `frame_style`, `source_color/width/style` y `connector_color/width/style`. Color None = el
  del marco; grosor None = "Auto" = la mitad del grosor del marco (como siempre); estilos de siempre: marco
  continuo, origen de rayas, conector continuo. Con los valores por defecto el dibujo es identico (el origen de
  rayas de 6/4 px sale de `dash_pattern(DASHED, 2)`).
- El contorno navy que da contraste (60 % de opacidad, ancho + 2) es SIEMPRE continuo, incluso bajo rayas o
  puntos: es parte del diseno de la lupa. El del conector circular son dos tangentes con el mismo estilo.
- Panel: secciones (Marco del lente, Zona de origen, Conector, Resplandor) con color, grosor y estilo, todos con
  restablecer; sin conector se ocultan los controles del conector. El panel ahora esta en un `QScrollArea` y las
  paginas que no se ven no cuentan para su alto (`_fit_page_size`).

### Texto: color de la letra, opacidad y estilos "Alerta 2" / "Nota 2"

- `TextLabel.opacity` (0 a 1, 1 por defecto) atenua TODA la etiqueta: letra, fondo y borde. El fondo ademas
  conserva su `bg_opacity` propio (queda `bg_opacity * opacity`). `PText.opacity` es nuevo; el SVG escribe
  `opacity="..."` en el `<text>` solo si es menor a 1 (al 100 % el SVG es identico al de siempre) y en una letra
  con contorno atenua letra y contorno juntos. El pintor de Qt usa `setOpacity`. Un JSON viejo sin la clave abre
  al 100 %; un valor invalido tambien.
- El panel de texto suma "Color letra" (valor de fabrica `#F1EBDF`; boton "Marca" y doble clic en la etiqueta
  lo restablecen) y "Opacidad" (0 a 100 %, con restablecer). `_ColorRow` acepta ahora el texto y el tooltip de su
  boton de restablecer.
- `TEXT_PRESETS` suma `alerta2` (fondo `#D32F2F`, borde `#8E1B1B`, letra blanca, mismo borde de 3 px que Alerta)
  y `nota2` (fondo `#FFF3A3`, borde `#E0C84A`, letra `#333333`, mismo borde que Nota). Los presets solo fijan
  colores: tamano, alineacion, negrita y opacidad se conservan al elegirlos. Aparecen en el combo "Estilo" junto
  a Nota y Alerta (`PRESET_LABELS`). Las originales no cambiaron.
- Error corregido de paso: al envolver el panel en un `QScrollArea` la pagina se estiraba y el formulario
  repartia el espacio sobrante entre sus filas; ahora la pagina va en un contenedor con relleno debajo.

## Portada: subtitulo

- `CoverConfig` suma `subtitle_position` (abajo-derecha, abajo-izquierda, abajo-centro), `subtitle_text_color`
  (`#F1EBDF`), `subtitle_bg_color` (`#1B3350`), `subtitle_bg_opacity` (0.90), `subtitle_border_color` (`#2F80D6`),
  `subtitle_border_width` (2 px, 0 a 12) y `subtitle_font_size` (36). Van en los presets (`config_to_dict`); un
  preset viejo abre con estos valores, y una posicion desconocida usa la de siempre. El TEXTO del subtitulo no
  es parte del preset (igual que el titulo).
- `geometry.compute_subtitle_layout(config, texto, measure)` devuelve la franja ya resuelta (`SubtitleLayout`)
  o None si el texto esta vacio. Reutiliza `wrap_title` (la misma logica del titulo: parte en dos lineas y, si
  aun asi no cabe, achica la letra) y `layout_text_lines`; ultimo recurso: achica proporcionalmente. El margen al
  borde es 24 px a 1584 px de ancho y escala con el lienzo. El texto se respeta tal cual (no pasa por
  `normalize_title`). Nunca se sale del lienzo (hay un test con textos absurdos en cada posicion).
- `build_svg(..., subtitle=layout)` agrega UN solo `<rect>` redondeado (sin acento en L ni sombra) y el texto,
  encima del titulo. La opacidad es solo del `fill-opacity`; el borde y el texto van al 100 %. El borde se
  dibuja HACIA ADENTRO de la caja, asi el tamano y la posicion de la franja no cambian con el grosor.
- La vista previa (`PreviewWidget.request_render(..., subtitle)`) y la exportacion usan el mismo `build_svg` y
  el mismo rasterizador (`resvg`; el proyecto no usa cairosvg): hay un test de que dan los mismos bytes.

### Lupa: resplandor del conector

- `Magnifier.connector_glow` (apagado por defecto; su color es `glow_color`, el mismo del resplandor del lente). Es un
  halo de 9 lineas apiladas por segmento (la mas ancha y tenue primero), con el mismo alcance y progresion que los
  anillos del lente (`style.GLOW_RINGS`, opacidad x `CONNECTOR_GLOW_STRENGTH`). Llevan las rayas y el remate del
  conector y van DEBAJO de su contorno navy y de su trazo. Se probo primero la franja simple de las flechas (30 %) y
  se veia demasiado tenue sobre un conector delgado. Sin conector no hay halo. El panel tiene "Resplandor del
  lente" y "Resplandor del conector"; el color se ve si cualquiera de los dos esta activo.

### Portada: arrastrar el subtitulo (y el bug de la banda)

- `CoverConfig.subtitle_x/subtitle_y`: esquina superior izquierda elegida arrastrando (None = la del combo;
  van juntas; un valor danado o incompleto en un preset se ignora). `compute_subtitle_layout` la respeta y la
  limita al lienzo. Elegir una posicion en el combo la suelta; el boton "Volver a la posicion automatica" tambien.
  Se redondea a pixeles enteros: un borde de 2 px entre dos pixeles sale difuso.
- `PreviewWidget` conoce el rect de la banda y el del subtitulo (la senal `finished` ahora trae los dos) y decide
  que se arrastra con `_target_at`: el subtitulo gana si se solapan (esta dibujado encima). Emite
  `bandRepositioned` o `subtitleRepositioned`.
- BUG (existia desde el primer commit del arrastre): `_on_band_dragged` actualizaba la configuracion pero NUNCA pedia
  redibujar (`SliderSpinBox.set_value` bloquea las senales), asi que tras el primer arrastre la vista previa se
  quedaba en la primera posicion y la zona "agarrable" (calculada con la imagen vieja) no coincidia: el titulo
  parecia trabado. Ahora ambos manejadores llaman a `_trigger_preview_render()` (el render coalesce los pedidos).
  `tests/test_cover_drag.py` lo cubre con renders reales en el hilo.

### Portada: subtitulo con degradado, contorno del texto y coordenadas

- `CoverConfig` suma `subtitle_gradient` (apagado), `subtitle_bg_color2` (`#3182DF`, el azul de acento de la marca),
  `subtitle_gradient_direction` (`GradientDirection`: horizontal, vertical, diagonal), `subtitle_outline_enabled`
  (apagado) y `subtitle_outline_color` (`#B38E5D`, el del titulo). Presets viejos abren con los defaults; en
  `config_from_dict` un color que no sea `#RRGGBB`, un booleano que no sea booleano o una direccion desconocida usan
  el valor de siempre.
- Degradado: UN `linearGradient` (`subtitleGradient`) de dos colores, del `subtitle_bg_color` al `bg_color2`, con el
  vector (0,0)-(1,0) / (0,0)-(0,1) / (0,0)-(1,1) segun la direccion. Rellena el rectangulo con
  `fill="url(#subtitleGradient)"` y la `fill-opacity` del fondo aplica a los dos colores; el borde y el texto siguen
  al 100 %. Es bicolor por ahora; para mas colores bastaria con que el modelo pase a una lista de paradas.
  Boton "Colores de marca (banda -> acento)": primer color = color de la banda, segundo = el del acento.
- Contorno del texto: `stroke` + `paint-order="stroke fill"` con el grosor automatico del titulo
  (`max(2, tamano * 0.02)`), `stroke-linejoin="round"`. Es independiente del "Grosor del contorno", que es el borde
  de la franja.
- Coordenadas: X / Y (esquina superior izquierda de la franja, px del lienzo) y cuatro botones de flecha que la
  mueven de a N px (por defecto 10; derecha + abajo = diagonal). Siempre muestran donde esta la franja (automatica,
  arrastrada o escrita: `_sync_subtitle_position_spins`), con limites dinamicos para que no salga del lienzo, y se
  apagan sin texto de subtitulo. Escribirlas fija `subtitle_x/y` (se guardan en el preset). Los numeros de varios
  digitos se aplican al terminar de teclear (`keyboardTracking` apagado). Los botones reutilizan
  `_on_subtitle_dragged` (redondeo a px enteros y limite al lienzo).
- Maquetacion: las filas nuevas hicieron el panel izquierdo mas ancho que su zona y se recortaba por la derecha; los
  botones de flecha son de 30 px y el panel tiene ancho minimo 490 (maximo 540). El test compara el ancho del grupo
  Subtitulo contra el de los demas grupos (un numero fijo cambia con las fuentes de cada plataforma).

### Colores personalizados que se guardan entre sesiones

- Bug (no causado por los cambios del proyecto): el selector de color de Qt guarda los "colores personalizados" solo
  en memoria (16 espacios que arrancan en blanco en cada sesion) y la app no los guardaba en ningun lado. En Windows
  este Qt usa su propio dialogo, no el nativo, asi que `QColorDialog.setCustomColor` / `customColor` mandan.
- `core/user_settings.py` (sin Qt): guarda los 16 espacios en `custom_colors.json` dentro de la carpeta de datos del
  USUARIO (`%APPDATA%\Cover Studio`; `$XDG_CONFIG_HOME/cover-studio` fuera de Windows; la variable
  `COVER_STUDIO_HOME` la cambia). Escritura atomica (temporal + `os.replace`), tolerante a archivos danados (vacios, a
  medias, tipos raros: cada espacio invalido queda vacio y nunca impide abrir la app) y con `UserSettingsError` clara.
- `ui/widgets.py`: `restore_custom_colors()` (una vez por sesion, al abrir el selector por primera vez) y
  `persist_custom_colors()` (al cerrar el dialogo, tambien al cancelar, solo si cambio algo; un fallo al escribir
  avisa por stderr y sigue). `tests/conftest.py` aisla `COVER_STUDIO_HOME` en cada prueba: las pruebas nunca tocan el
  APPDATA real. Cambiar de equipo: basta copiar ese JSON.

### Portada: degradado en el borde del subtitulo

- `CoverConfig.subtitle_border_gradient` (apagado) y `subtitle_border_color2` (`#21B868`, el verde de la banda): el
  borde va de `subtitle_border_color` a `subtitle_border_color2` con su PROPIO `linearGradient`
  (`subtitleBorderGradient`), independiente del del relleno, y usa la misma direccion (horizontal, vertical o
  diagonal). Sigue al 100 % de opacidad. Con grosor 0 no se emite. Si ambos estan encendidos hay dos gradientes en un
  solo `<defs>`.
- Interfaz: "Degradado en el relleno" y "Degradado en el borde", cada uno con su segundo color; la direccion y el
  boton "Colores de marca (banda / acento)" son comunes y solo se ven si alguno esta encendido. El boton pone el
  relleno de la banda al acento y el borde del acento a la banda (al reves, para que el borde se distinga); solo
  toca lo que esta encendido y, si no hay nada, enciende los dos.

### Pendiente (fase futura): colores de marca configurables

- Hoy los colores de marca estan fijos en el codigo: Portada en los defaults de `CoverConfig` (banda `#21B868`,
  acento `#3182DF`, texto `#F1EBDF`...) y `presets/default.json`; Anotar en `core/annotate/style.py` y
  `palette.BRAND_PALETTE`. Para usar la herramienta en otra marca o venderla, la idea es UN archivo de marca (p. ej.
  `brand.json`, con nombre de la marca y colores con nombre) que alimente los defaults de las dos pestanas, el boton
  "Restaurar colores de marca" y el degradado del subtitulo. La infraestructura de datos de usuario de
  `core/user_settings.py` ya sirve de base.
