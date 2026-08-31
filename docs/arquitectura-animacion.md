# Arquitectura — exportar portadas animadas (video / GIF)

Diseño de Opus (sesión de la semana pasada), condensado y guardado aquí porque solo
vivía en la conversación. Pensado para implementarse por fases cortas con Sonnet.

Estado: **fase 0 hecha** (`core/easing.py`, `core/text_metrics.py`). El resto pendiente.

Objetivo: exportar la portada con una entrada animada sutil (banda, acento en L y título
por palabras) a MP4 (YouTube, Shorts, Facebook, LinkedIn), GIF y WebP, y poder generar
lienzos verticales 9:16.

---

## 1. La decision que lo cambia todo (medida en esta maquina)

Interpolar el `CoverConfig` y llamar `build_svg` + `render_png_bytes` en cada frame es
inviable:

| Operación (1920x1080) | Mediana |
|---|---|
| `build_svg` con foto + `render_png_bytes` (enfoque ingenuo) | **644 ms** |
| Solo overlay SVG (banda+acento+texto) con sombra | 294 ms |
| Solo overlay SVG, sin sombra | 179 ms |
| SVG vacío a 1080p | 78 ms |
| armar el string SVG con foto en base64 | 0.2 ms |

- El cuello de botella **no** es el base64 (0.8 ms): es que resvg re-decodifica y
  re-escala el JPEG en cada llamada y luego codifica un PNG de 2.2 MB que Pillow
  vuelve a decodificar.
- **`resvg_py` no libera el GIL**: 4 hilos dan 1.02x. Solo `multiprocessing` escala
  (6.5x con 12 procesos, incluyendo el arranque). Los hilos no sirven.
- Enfoque ingenuo: 150 frames x 644 ms = **97 s** en un hilo.

**Solución: no animar el SVG; animar capas ya rasterizadas** (lo que hace GSAP: anima
`transform` y `opacity`, no re-calcula el DOM). Cada capa se rasteriza UNA vez con resvg
y por frame solo se aplica translate / scale / opacity / crop con Pillow.
Medido: composición 15.2 ms/frame; pipeline composición + x264 16.4 ms/frame;
**150 frames a 1080p en ~2.5 s, un solo hilo, sin multiprocessing** (40x más rápido).

resvg respeta el offset del `viewBox`, así que cada sprite se rasteriza solo sobre su
caja (`viewBox="90 80 1590 210"` da exactamente la banda, con su alfa 0.9 intacto).

Costos por frame en Pillow (1080p): `alpha_composite` de un sprite 3.8 ms; `crop`
(wipe/reveal) 0.01 ms; `resize` de una palabra 0.4 ms; opacidad global 0.8 ms;
`convert("RGB").tobytes()` 5.3 ms.

Lo que se pierde: no se anima geometría vectorial (ancho de banda como rectángulo real,
`accent_shift`, `corner_radius`, `font_size`). El "reveal" de la banda se hace con `crop`
(cubre el 90% del caso). Escalas pequeñas (0.92 → 1.0) se ven bien en bitmap; los
sprites de texto se rasterizan a 1.2x para que el escalado sea siempre reducción.
Un `RenderMode.VECTOR` (lento, ~15 s con multiprocessing) queda como escape, sin UI.

## 2. Decisiones

| Decisión | Por qué |
|---|---|
| `AnimationConfig` separado de `CoverConfig` | No contamina `presets/*.json`; un diseño admite varias animaciones; interpolar `CoverConfig` obliga a re-rasterizar. `CoverConfig` = estado final; la animación describe cómo se llega. |
| Sprites + composición con Pillow | 16.4 ms/frame vs 644. |
| Pipe `rawvideo rgb24` a stdin de ffmpeg | Sin temporales ni re-codificar PNG (16.4 ms/frame end-to-end). |
| Sin `imageio` | Duplica ffmpeg y suma otro binario de ~30 MB. |
| `TextUnit.WORD` por defecto | Por letra se pierde el kerning entre `<text>` y el error de medición se acumula; "slight" es lo que se pidió. |
| `MeasureFn` inyectado | Es el patrón de `wrap_title`; mantiene `core/` sin Qt. |
| GIF forzado a 15 fps / 640 px | A 1080p30 pesaría decenas de MB (con esos límites: ~476 KB). |
| WebP animado sí, pero etiquetado | YouTube/Facebook/LinkedIn no lo aceptan como video; sirve para blog y WhatsApp. |
| `probe_ffmpeg() -> FFmpegInfo \| None`, nunca lanza | ffmpeg viene del paquete winget de yt-dlp: puede moverse; su ausencia es un estado esperado. |

## 3. Archivos

```
core/
  easing.py          [HECHO] curvas de Penner, sin dependencias
  text_metrics.py    [HECHO] MeasureFn con Pillow/FreeType (sin Qt)
  geometry.py        MODIFICAR: refactor aditivo (extraer helpers puros de build_svg)
  text_utils.py      MODIFICAR: TextUnit, TextToken, split_line_tokens
  presets.py         MODIFICAR: serializar AnimationConfig
  animation.py       NUEVO  modelo, presets de animación, muestreo
  layers.py          NUEVO  descomposición en capas + SVG por capa
  canvas_adapt.py    NUEVO  adaptar geometría 16:9 a otros lienzos
  video.py           NUEVO  probe_ffmpeg, build_ffmpeg_args, FrameSink
  render_anim.py     NUEVO  sprites, compositor, orquestador
ui/
  animation_panel.py, export_task.py   NUEVOS
  main_window.py     MODIFICAR: CANVAS_PRESETS con metadata, formato, progreso
  preview.py         MODIFICAR: reproducción en vivo (fase 7)
presets/anim/subtle.json, editorial.json, bounce.json, shorts-9x16.json   NUEVOS
```

## 4. Modelo (resumen de firmas)

```python
class LayerKind(str, Enum):   PHOTO, ACCENT, BAND, TEXT
class RevealDirection(str, Enum): NONE, LEFT_TO_RIGHT("ltr"), RIGHT_TO_LEFT("rtl"), TOP_TO_BOTTOM("ttb"), BOTTOM_TO_TOP("btt")
class StaggerFrom(str, Enum): START, END, CENTER

@dataclass(frozen=True)
class Transform:               # estado de UNA capa en UN instante; identidad = portada estática
    dx=0.0; dy=0.0; scale=1.0; opacity=1.0; reveal=1.0

@dataclass(frozen=True)
class TrackSpec:               # cómo entra una familia de capas; en start+duration = identidad
    kind; start=0.0; duration=0.8; easing=Easing.OUT_CUBIC; overshoot=1.0
    from_dx=0.0; from_dy=0.0; from_scale=1.0; from_opacity=0.0
    reveal_direction=NONE; stagger=0.0; stagger_from=START

@dataclass
class AnimationConfig:
    fps=30; duration=4.0; text_unit=TextUnit.WORD; ken_burns=0.0
    tracks=(); freeze_tail=True

track_progress(track, time_s, index, count) -> float     # con stagger y easing
sample_transform(track, time_s, index=0, count=1) -> Transform
frame_times(anim) -> list[float];  total_frames(anim) -> int
```

La duración del clip se valida contra `start + (count-1)*stagger + duration`: la UI avisa
si el texto no alcanza a entrar antes de que termine el video (el bug de usabilidad nº 1).

Presets: **Sutil** (default: banda reveal LTR 0.5 s out-quint; acento +0.08 s; texto por
palabra `from_dy=+18`, stagger 0.06, out-cubic 0.45 s; termina en 1.2 s y se congela),
**Editorial** (banda desde la izquierda, texto por línea con fade), **Rebote**
(`out-back` overshoot 1.0, `from_scale=0.94`), **Estático** (sin tracks).

Easing: `out-back` con overshoot por defecto **1.0** (rebase real de 3.7%, medido). El
diseño original decia 0.6 "~4%", pero 0.6 rebasa solo 1.25% (casi imperceptible); el
1.70158 de Penner rebasa 10%. Tabla medida: 0.6 -> 1.25%, 0.8 -> 2.3%, 1.0 -> 3.7%,
1.1 -> 4.5%, 1.4 -> 7.1%, 1.70158 -> 10%.

## 5. Capas, sprites y texto

- `build_svg` **no cambia su firma ni su comportamiento.** Se extraen a funciones puras
  `svg_document`, `shadow_filter_defs`, `band_rect_svg`, `accent_path_svg`,
  `text_element_svg`, `photo_element_svg`, y `build_svg` pasa a componerlas.
  Criterio: los tests actuales pasan sin cambios y el PNG sale **byte-idéntico**.
- `build_layer_plan(config, lines, font_size, measure, text_unit) -> LayerPlan`; la foto
  no es capa SVG (la abre Pillow directo).
- Padding del bbox de texto por la sombra: `max(24, font_size * 0.35)` a cada lado.
  La sombra solo va en las capas de texto (62 ms con filtro vs 5 ms sin él).
- Con foto ausente el fondo es `#6E6E6E`: `load_background` debe replicarlo o el video
  sale distinto al PNG estático (divergencia silenciosa).
- Partir el texto por tokens midiendo **prefijos**: `x = measure(line[:i]) + measure(tok)/2
  - measure(line)/2`. OJO: esto NO absorbe el kerning como se creia. Pillow sin `raqm`
  (el caso aqui: Pillow 12.3.0, raqm False) no aplica kerning GPOS (`AV` mide igual que
  `A`+`V`), pero resvg si lo aplica: la medicion sobreestima unos px en pares como AV/To y
  el error se acumula por linea. Para el modo por palabra es tolerable; si el test RMS de la
  fase 3 lo delata, medir con el propio resvg (renderizar cada prefijo) en vez de Pillow.
- `compose_frame(background, sprites, transforms, canvas, ken_burns_zoom)`;
  `render_frame_at(job, measure, t)` es la puerta que permite probar y previsualizar sin
  ffmpeg.
- Test de no regresión clave: en `t >= fin de la animación` el frame compuesto coincide
  con `render_png_bytes(build_svg(...))` dentro de una tolerancia RMS (~2/255), nunca
  igualdad exacta (Pillow no compone en espacio lineal).

## 6. Video (`core/video.py`)

- `probe_ffmpeg()` (cacheada pero invalidable; se llama al arrancar y antes de cada export).
- **MP4:** `-f rawvideo -pix_fmt rgb24 -s WxH -r FPS -i pipe:0 -c:v libx264 -preset slow
  -crf 16|20|24 -pix_fmt yuv420p -movflags +faststart` (`yuv420p` es obligatorio o
  YouTube/Facebook lo rechazan).
- **GIF:** una pasada, `fps=15,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=
  stats_mode=diff[p];[b][p]paletteuse=dither=bayer`.
- **WebP animado** (`libwebp_anim`); **secuencia PNG** como salida sin ffmpeg (válida para
  importar en DaVinci Resolve).
- **Trampa:** hay que drenar el stderr de ffmpeg en un hilo aparte o el buffer del pipe se
  llena y todo se cuelga sin traceback; capturar `BrokenPipeError` y convertirlo en
  `VideoError` con la cola del stderr.
- Sin ffmpeg: el combo de formato deja solo "Secuencia PNG" y una etiqueta explica cómo
  instalarlo (`winget install Gyan.FFmpeg`). Nunca un traceback.

## 6b. UI

`ExportTask(QRunnable)` con señales `progress/finished/failed/cancelled`, cancelación
cooperativa con `threading.Event`, `QThreadPool` dedicado con 1 hilo. Barra inline +
botón Cancelar (no diálogo modal). El `MeasureFn` se construye en el hilo de UI; con
Pillow (fase 0) deja de haber Qt de por medio. Con formato estático el botón dice
"Generar"; con animado, "Exportar animación". Ruta de salida: cambia la extensión.
Reproducción en vivo (fase 7): `compose_frame` a 800 px cuesta ~4 ms, alcanza para 30 fps
con un `QTimer`.

## 7. Lienzos verticales (9:16)

La geometría 16:9 se ve mal en vertical (banda de 210 px sobre 1920 de alto; título que no
cabe; banda pegada arriba, donde Shorts pone su UI). Propuesta:
`CANVAS_PRESETS` como `tuple[CanvasPreset, ...]` con plataforma y `video_ready`;
`adapt_config_to_canvas(config, target, source=None) -> CoverConfig` (escala tipográfica
por ancho, margen superior por alto; en vertical `CENTER` y `max_lines >= 3`); checkbox
"Adaptar geometría al cambiar de tamaño". **Ninguna transformación automática produce una
composición vertical buena**: se entrega además un `presets/shorts-9x16.json` afinado a mano.
Ojo: `_apply_config_to_widgets` documenta un aliasing con `self.config`; respetarlo al
tocar `_on_canvas_preset_changed`, y reescribir el `next(...)` que compara `size ==
config.canvas` al cambiar `CANVAS_PRESETS`.

## 8. Fases

0. **[HECHA]** `easing.py` + `text_metrics.py`, con tests. No toca nada existente.
1. Refactor aditivo de `geometry.py` (byte-idéntico).
2. `animation.py`, `layers.py`, `split_line_tokens`, serialización. Sin renderizar.
3. `render_anim.py`: sprites, `compose_frame`, `render_frame_at`, test RMS. Sin ffmpeg.
4. `video.py`: MP4 y secuencia PNG primero; GIF y WebP después.
5. UI: export task, panel, formato, progreso, degradación sin ffmpeg.
6. Lienzos verticales + `shorts-9x16.json`.
7. Reproducción en vivo (en valor percibido es lo primero; adelantarla si la fase 3 sale limpia).

## 9. Riesgos conocidos

1. `resvg_py` no libera el GIL: no acelerar con hilos.
2. `wrap_title` es O(n³) en palabras: llamarlo una vez antes de construir el plan, no por frame.
3. Deriva de medición Qt vs resvg: mitigada con `pillow_measure_fn` (fase 0; mide a 512 px
   y escala, porque FreeType redondea el tamaño y las métricas a pixeles; sin raqm no hay
   kerning, ver §5). **Medido contra el ancho de tinta de resvg (Georgia 78 px): Qt 0.77 px de
   error medio, Pillow 2.4-3.8 px y siempre por encima.** El diseño original decia lo contrario
   ("FreeType esta mas cerca de resvg que Qt"): es falso aqui. Pillow vale por no depender de Qt
   (hilo de export, CLI, tests) y porque su error es conservador, no por ser mas exacto. Si la
   exactitud del posicionamiento por palabra importa, medir con el propio resvg. Cambiar la UI
   a Pillow puede mover unos px el wrap de títulos existentes; el modelo Qt queda como
   "legacy" para banners estáticos.
4. Deadlock del stderr de ffmpeg (ver §6).
5. ffmpeg depende del paquete de yt-dlp: sondear antes de cada export.

## 10. Cambios del repo desde que se diseño esto

- Existe `core/annotate/text_measure.py` (mide solo con Arial). Cuando convenga, que use
  `core/text_metrics.py` para tener una sola implementación.
- El README se guardaba en UTF-16; ya es UTF-8. Cualquier edición debe conservarlo.
- `tests/conftest.py` descarta por defecto el diálogo de cambios sin guardar de la pestaña
  Anotar (es modal y colgaba la suite). Si se agregan diálogos modales nuevos, hacer lo
  mismo.

---

## 11. Firmas pendientes (fases 1 a 6)

Completan lo que el resumen de arriba solo nombra. Son el contrato: si una firma cambia al
implementarla, actualizar esta seccion.

### Fase 1 — `core/geometry.py`: helpers puros extraidos de `build_svg`

```python
def svg_document(view_box: tuple[float, float, float, float], width: int, height: int,
                 body: Sequence[str]) -> str
def shadow_filter_defs(config: CoverConfig) -> str
def band_rect_svg(config: CoverConfig, band: BandGeometry, opacity: float) -> str
def accent_path_svg(config: CoverConfig, band: BandGeometry, opacity: float) -> str
def text_element_svg(config: CoverConfig, text: str, x: float, y: float,
                     font_size: float, use_shadow: bool) -> str
def photo_element_svg(canvas: CanvasSize, data_uri: str) -> str
```

`build_svg(config, lines, font_size, photo_path)` conserva firma y comportamiento y pasa a ser
la composicion de estos. Criterio de aceptacion: los tests actuales de `test_geometry.py`
pasan sin tocarlos y `render_png_bytes(build_svg(...))` es byte-identico al de antes (un
test guarda el PNG de referencia generado ANTES del refactor).

### Fase 2 — `core/text_utils.py`, `core/animation.py`, `core/layers.py`, `core/presets.py`

```python
class TextUnit(str, Enum):  LINE = "line"; WORD = "word"; LETTER = "letter"

@dataclass(frozen=True)
class TextToken:
    text: str
    line_index: int
    order: int          # indice global en el titulo: gobierna el stagger
    x_offset: float     # centro del token relativo al centro de la linea
    width: float

def split_line_tokens(line: str, measure: MeasureFn, font_size: float, unit: TextUnit,
                      line_index: int = 0, start_order: int = 0) -> list[TextToken]

def sample_plan(anim: AnimationConfig, plan: LayerPlan, time_s: float) -> list[Transform]
    # un Transform por capa del plan, en su orden; capas sin track -> identidad

@dataclass(frozen=True)
class Layer:
    kind: LayerKind
    order: int                                  # indice dentro de su familia (stagger)
    box: tuple[float, float, float, float]      # x, y, w, h en px del lienzo, con padding
    anchor: tuple[float, float]                 # punto fijo del scale, px del lienzo
    svg: str                                    # SVG autocontenido de ESTA capa

@dataclass(frozen=True)
class LayerPlan:
    canvas: CanvasSize
    layers: tuple[Layer, ...]                   # orden de dibujo, atras -> adelante

def build_layer_plan(config: CoverConfig, lines: Sequence[str], font_size: float,
                     measure: MeasureFn, text_unit: TextUnit = TextUnit.WORD) -> LayerPlan
    # NO incluye la foto; reusa compute_band_geometry, compute_accent_path, layout_text_lines

def anim_config_to_dict(anim: AnimationConfig) -> dict
def anim_config_from_dict(data: dict) -> AnimationConfig
def save_anim_preset(anim: AnimationConfig, name: str, presets_dir: Path) -> Path
def load_anim_preset(path: Path) -> AnimationConfig
```

Reglas de la fase 2: cada `svg` de capa es un documento cerrado y escapa el texto con
`escape_xml`; los `box` caen dentro del lienzo; el padding de la sombra es
`max(24, font_size * 0.35)`; el acento NO se solapa con la banda (la L ya resta el interior).
Los presets de animacion usan el mismo mecanismo que `presets.py` (`asdict` + `.value` de
los enums + `fields()` para ignorar claves desconocidas).

### Fase 3 — `core/render_anim.py`

```python
class RenderMode(str, Enum):  SPRITE = "sprite"; VECTOR = "vector"   # VECTOR: sin UI, lento

@dataclass(frozen=True)
class Sprite:
    layer: Layer
    image: Image.Image        # RGBA recortada al box (sobremuestreada si es texto)
    oversample: float

def rasterize_sprites(plan: LayerPlan, oversample_text: float = 1.2) -> list[Sprite]
    # una llamada a resvg por capa (~15, <1 s, una sola vez por export)

def load_background(photo_path: Path | None, canvas: CanvasSize) -> Image.Image
    # exif_transpose + recorte "cover" (equivale a preserveAspectRatio xMidYMid slice) + RGBA;
    # sin foto -> relleno #6E6E6E, IGUAL que build_svg (si no, el video sale distinto al PNG)

def compose_frame(background: Image.Image, sprites: Sequence[Sprite],
                  transforms: Sequence[Transform], canvas: CanvasSize,
                  ken_burns_zoom: float = 0.0) -> Image.Image
    # orden: fondo -> sprites. reveal -> crop; opacity -> point() sobre el alfa;
    # scale -> resize alrededor del anchor; dx/dy -> offset del alpha_composite

ProgressFn = Callable[[int, int], None]      # (frame_actual, total)
CancelFn = Callable[[], bool]                # True -> abortar

@dataclass
class AnimationJob:
    config: CoverConfig
    anim: AnimationConfig
    lines: list[str]
    font_size: float
    photo_path: Path | None
    output_path: Path
    output_format: OutputFormat
    quality: VideoQuality = VideoQuality.HIGH
    mode: RenderMode = RenderMode.SPRITE

def render_animation(job: AnimationJob, measure: MeasureFn, progress: ProgressFn | None = None,
                     should_cancel: CancelFn | None = None) -> Path
    # plan -> sprites -> fondo -> loop de frames -> FrameSink. Consulta should_cancel() en cada
    # frame; al cancelar borra el archivo parcial y lanza ExportCancelled. Devuelve la ruta.

def render_frame_at(job: AnimationJob, measure: MeasureFn, time_s: float) -> Image.Image
    # un frame suelto: para la vista previa en vivo y para los tests (sin ffmpeg)
```

Criterio de aceptacion de la fase 3: en `t >= fin de la animacion`, el frame compuesto
coincide con `render_png_bytes(build_svg(...))` con RMS <= ~2/255 (lienzo chico, 480x270, para
que corra rapido). Nunca igualdad exacta.

### Fase 4 — `core/video.py`

```python
class VideoError(Exception): ...
class ExportCancelled(Exception): ...

class OutputFormat(str, Enum):  MP4 = "mp4"; GIF = "gif"; WEBP = "webp"; PNG_SEQ = "png-seq"
class VideoQuality(str, Enum):  HIGH = "high"; BALANCED = "balanced"; SMALL = "small"
    # mp4: HIGH -> -preset slow -crf 16; BALANCED -> -crf 20; SMALL -> -preset veryfast -crf 24

@dataclass(frozen=True)
class FFmpegInfo:
    path: Path
    version: str
    has_libx264: bool
    has_libwebp: bool
    has_gif: bool

def probe_ffmpeg() -> FFmpegInfo | None
    # shutil.which("ffmpeg") + "ffmpeg -encoders". NUNCA lanza. Cacheada pero invalidable.

def missing_ffmpeg_message(fmt: OutputFormat) -> str
    # mensaje accionable en espanol: menciona winget install Gyan.FFmpeg y que PNG y secuencia
    # PNG si funcionan sin ffmpeg

def build_ffmpeg_args(fmt: OutputFormat, canvas: CanvasSize, fps: int, output_path: Path,
                      quality: VideoQuality) -> list[str]
    # funcion pura: se testea con un snapshot de la lista de argumentos

class FrameSink:
    def __init__(self, fmt: OutputFormat, canvas: CanvasSize, fps: int, output_path: Path,
                 quality: VideoQuality) -> None
    def __enter__(self) -> "FrameSink"
    def write(self, frame_rgb: bytes) -> None       # BrokenPipeError -> VideoError con la cola del stderr
    def abort(self) -> None
    def __exit__(self, *exc) -> None                # drena stderr en un hilo aparte (si no, se cuelga)
```

### Fase 5 — `ui/export_task.py`

```python
class _ExportSignals(QObject):
    progress = Signal(int, int)       # frame actual, total
    finished = Signal(str)            # ruta escrita
    failed = Signal(str)
    cancelled = Signal()

class ExportTask(QRunnable):
    def __init__(self, job: AnimationJob, measure: MeasureFn) -> None
    def cancel(self) -> None          # threading.Event; render_animation lo consulta por frame
    def run(self) -> None
```

`QThreadPool` dedicado con `setMaxThreadCount(1)`, separado del pool de la vista previa. La
UI muestra `f"Frame {i}/{n} - {eta:.0f}s restantes"` en la barra de estado. `MeasureFn`:
construirlo en el hilo de UI y pasarlo al task, o usar `pillow_measure_fn` (sin Qt).

### Fase 6 — `core/canvas_adapt.py` y `ui/main_window.py`

```python
REFERENCE_CANVAS = CanvasSize(1920, 1080)

def adapt_config_to_canvas(config: CoverConfig, target: CanvasSize,
                           source: CanvasSize | None = None) -> CoverConfig
    # NUEVO objeto, no muta. Escala por ancho: font_size, band_height, accent_shift,
    # corner_radius, inner_margin, band_margin_left, band_width. band_margin_top por alto.
    # Lienzo vertical (aspect < 1): vertical_position -> CENTER y max_lines -> max(max_lines, 3).

@dataclass(frozen=True)
class CanvasPreset:
    label: str
    size: CanvasSize | None           # None = "Personalizado"
    platform: str                     # "YouTube", "Shorts/Reels", "Meta/LinkedIn", "Feed", "Blog"
    video_ready: bool

CANVAS_PRESETS: tuple[CanvasPreset, ...] = (
    CanvasPreset("1920 x 1080 (16:9) - YouTube", CanvasSize(1920, 1080), "YouTube", True),
    CanvasPreset("1080 x 1920 (9:16) - Shorts / Reels", CanvasSize(1080, 1920), "Shorts/Reels", True),
    CanvasPreset("1080 x 1350 (4:5) - Facebook / LinkedIn", CanvasSize(1080, 1350), "Meta/LinkedIn", True),
    CanvasPreset("1080 x 1080 (1:1)", CanvasSize(1080, 1080), "Feed", True),
    CanvasPreset("1200 x 630 (Open Graph)", CanvasSize(1200, 630), "Blog", False),
    CanvasPreset("Personalizado", None, "", True),
)
```

Al pasar `CANVAS_PRESETS` de dict a tupla hay que reescribir los usos de `CANVAS_PRESETS.items()`
y el `next(...)` que compara `size == config.canvas` en `_apply_config_to_widgets`; si no, la
seleccion del combo se rompe en silencio. `_on_canvas_preset_changed` hoy muta
`self.config.canvas` directo: primero adaptar y luego aplicar (respetar el contrato del
docstring sobre el aliasing).

---

## 12. Tests por archivo

Todo se prueba sin Qt gracias al `MeasureFn` inyectado. Fake de las pruebas:
`fake_measure(text, size) = len(text) * size * 0.55`.

| Archivo | Cubre |
|---|---|
| `test_easing.py` | [HECHO] f(0)=0 y f(1)=1 en todas; monotonia; rebase medido; `get_easing` desconocido. |
| `test_text_metrics.py` | [HECHO] resolucion de fuentes (skip si no hay Georgia), escala lineal, fallback, y error contra resvg. |
| `test_animation.py` | `sample_transform` antes de `start` = estado `from_*` y en `start+duration` = identidad exacta; stagger por indice y por `StaggerFrom`; `len(frame_times) == round(fps*duration)`; ida y vuelta de `AnimationConfig`. |
| `test_layers.py` | Conteo de capas por `TextUnit`; `box` dentro del lienzo; cada `svg` cerrado y con el texto ESCAPADO; el bbox de texto incluye el padding de la sombra. |
| `test_canvas_adapt.py` | 16:9 -> 9:16 divide `font_size` por 1.777...; vertical fuerza `CENTER` y `max_lines >= 3`; mismo lienzo = identidad; no muta la entrada. |
| `test_video.py` | `build_ffmpeg_args` como snapshot (mp4 lleva `-pix_fmt yuv420p`); con `probe_ffmpeg` en `None`, exportar mp4 lanza `VideoError` con mensaje accionable. **Ningun test invoca ffmpeg de verdad** (su presencia es fragil). |
| `test_render_anim.py` | `render_frame_at` devuelve una imagen del tamano del lienzo; en `t=0` con `from_opacity=0` la banda es invisible; el frame final coincide con el estatico (RMS). |

## 13. Criterios de aceptacion resumidos

1. **Fase 1:** PNG byte-identico y tests existentes intactos.
2. **Fase 2:** el modelo cierra (ida y vuelta de presets, capas dentro del lienzo); nada se renderiza todavia.
3. **Fase 3:** cualquier frame se puede generar sin ffmpeg y el frame final coincide con el estatico.
4. **Fase 4:** sin ffmpeg nunca hay traceback; MP4 y secuencia PNG primero, GIF y WebP despues.
5. **Fase 5:** exportar no congela la ventana, se puede cancelar, y falta de ffmpeg degrada a secuencia PNG.
6. **Fase 6:** un lienzo vertical no deja la banda pegada al borde superior.
