# Traspaso para la siguiente sesion

Leelo completo antes de tocar codigo. Lo escribio la sesion anterior para que esta pueda empezar
sin repetir descubrimientos ni preguntar lo que ya se decidio.

## 1. Que hay (estado al cerrar la sesion anterior)

Cover Studio: app de escritorio PySide6 en `D:\repos\cover_studio` (Windows, Python 3.14, venv en
`.venv`). Se abre con `run_cover_studio.bat` o `.vbs`. **431 tests pasan.**

- **Pestana "Portada"**: genera portadas 16:9 (foto + banda + titulo + acento en L), vista previa en
  vivo con hilo y debounce, arrastre de la banda, presets, guarda anti-sobrescritura.
- **Pestana "Anotar"**: anota capturas con la identidad de Excel Solutions. Herramientas: Seleccionar,
  Marcador (con flecha), Recuadro (sin flecha), Flecha, Paso, Texto, Pixelar, Lupa (circular, ovalada,
  rectangular con esquinas ajustables). Paleta de colores del documento + color propio por anotacion,
  margen extra, escala de trazo, deshacer/rehacer, guardar proyecto (`.anotar.json`), copiar,
  exportar PNG/SVG, aviso de cambios sin guardar.
- **Animaciones**: SOLO la fase 0 (`core/easing.py`, `core/text_metrics.py`). Fases 1 a 7 pendientes.

Documentos de diseno (fuente de verdad, leelos segun la tarea):
- `docs/arquitectura-anotar.md` — como esta hecha la pestana Anotar y por que.
- `docs/arquitectura-animacion.md` — diseno de las animaciones (video/GIF), con firmas y criterios.

Al empezar: corre `git status` y `git log --oneline -5`. El usuario hace los commits el mismo; si hay
cambios sin commitear de la sesion anterior, es lo ultimo que se hizo (colores y formas de lupa).

## 2. Como trabajar con este usuario

- Habla espanol. Directo, sin rodeos; reporta con honestidad lo que NO pudo probar.
- **Fases chicas y revisables.** Su limite semanal es real: no lances subagentes caros sin avisar
  (el diseno de las animaciones costo ~3% de su semana). Pide visto bueno antes de cada fase grande.
- Prefiere Opus para arquitectura y Sonnet para ejecutar. Si algo requiere redisenar, dilo y deja que
  elija; casi nunca hace falta.
- **Commits: no los hagas tu.** Dale los comandos en bloques ```bash``` separados (uno por comando, para
  el boton Run). Mensaje: texto plano, sin comillas ni apostrofes, maximo 10 palabras, **sin
  Co-Authored-By** (lo pidio explicitamente).
- Verifica con tests Y mirando el resultado (ver trampas). Cuando un dato del diseno se pueda medir,
  mide: la sesion anterior encontro tres afirmaciones falsas en el diseno de Opus (rebote del easing,
  que Pillow midiera mejor que Qt, que Pillow aceptara tamanos fraccionarios).
- Si el usuario pregunta "ya acabamos?", distingue entre generador de portadas, anotador y animaciones.

## 3. Backlog que el usuario ELIGIO (en este orden)

Los cuatro son para la pestana Anotar. Hazlos uno por uno, con tests y verificacion visual, y da el
commit de cada uno antes de empezar el siguiente.

### 3.1 Recortar la captura
Para "me pase de largo / necesito algo mas pequeno".
- Recomendado **no destructivo**: `AnnotationDoc.crop: Rect | None` en pixeles de la imagen fuente. Las
  anotaciones siguen en coordenadas de la fuente; el export y el lienzo muestran solo la region
  recortada (trasladar por `-crop.x, -crop.y`). Asi se puede deshacer y reabrir el proyecto.
- Herramienta "Recortar": arrastras el rectangulo (con asas), se aplica (deshacible), y un boton
  "Quitar recorte". Avisar si hay anotaciones fuera del recorte.
- Ojo con: `image_size` usado por export/padding/`required_padding`/hit-test, los pixelados y las
  lupas (siguen leyendo el bitmap COMPLETO), `view_layout` del lienzo, el sidecar JSON (`crop`
  opcional, proyectos viejos sin esa clave deben abrir igual).

### 3.2 Resaltador (highlighter)
- Nueva anotacion `Highlight(id, rect, color=None, opacity)` con relleno semitransparente sobre texto
  (como un marcador fluorescente), esquinas redondeadas opcionales.
- **Colores estandar de papeleria** (los de un resaltador de Office Depot): amarillo, verde, rosa,
  naranja, azul claro (valores sugeridos: #FFF200, #7CFC00, #FF69B4, #FFA500, #00BFFF; ajustalos mirando
  el resultado sobre fondo claro Y oscuro). Fila de muestras para elegir rapido + el selector de color
  completo para personalizados. Color por defecto en la paleta del documento (campo nuevo en `Palette`).
- Verifica si resvg soporta `mix-blend-mode: multiply` ANTES de depender de el; si no, usa alfa simple
  (~0.4) y que el pintor de Qt y el SVG den lo mismo. Mide, no supongas.
- Valora reutilizar la fila de muestras en los demas selectores de color (`ui/widgets.py`
  `ColorPickerButton`).

### 3.3 Zoom y desplazamiento del lienzo
Hoy la captura se ajusta a la ventana (maximo 2x) y no hay zoom: con capturas 4K se coloca con poca
precision.
- Rueda = zoom hacia el cursor; arrastrar con boton central (o espacio + arrastrar) = desplazar;
  botones "Ajustar" y "100%". El zoom es de VISTA: no cambia el export.
- `AnnotateCanvas.view_layout()` es el unico lugar que convierte pantalla <-> imagen
  (`view_to_image` / `image_to_view`); incorporar ahi zoom y desplazamiento y todo lo demas (hit-test,
  tolerancia de clic, asas, seleccion) hereda. La tolerancia ya se convierte con la escala de vista.
- Cuidado con el recorte de pantalla a "lo que se exportaria" (`setClipRect` en `paintEvent`) y con el
  margen extra.

### 3.4 Foco (spotlight) con dos modos: oscurecer o desenfocar
El usuario pidio el desenfoque SOLO para este caso: destacar una zona y desenfocar el resto.
- Anotacion `Spotlight(id, rect, shape, mode, strength)`; `shape` rectangular/redondeada/ovalada;
  `mode` = OSCURECER (capa oscura semitransparente fuera de la zona) o DESENFOCAR (blur gaussiano fuera
  de la zona, con `ImageFilter.GaussianBlur`; el radio escala con `style_scale`).
- **Un solo foco por documento** (varios huecos = union; complica sin aportar). Crear uno nuevo
  reemplaza el anterior.
- Se aplica al BITMAP, como el pixelado (`core/annotate/raster.py`), en este orden:
  pixelados -> recortes de lupa -> foco -> anotaciones. Asi las anotaciones y las lupas quedan nitidas
  encima. Debe estar en el SVG exportado igual que en pantalla.
- **Advertir en la interfaz que el desenfoque NO es para ocultar datos confidenciales** (para eso es
  Pixelar). El desenfoque es solo enfasis visual.

## 4. Trampas tecnicas (cada una costo tiempo)

- **Herramienta Bash**: los heredocs con comillas triples simples (`'''`) o con apostrofes sueltos hacen
  que el analizador del comando falle ("unexpected EOF"). Escribe los scripts de parche con la
  herramienta Write en el scratchpad y ejecutalos. Los parches usan una funcion `patch(path, pairs)`
  que verifica `count == 1` y solo escribe si TODOS los reemplazos coinciden (si falla, no deja cambios a
  medias).
- **`QT_QPA_PLATFORM=offscreen` en Windows no tiene fuentes**: el texto sale como cuadritos, incluidos los
  botones. Para MIRAR la interfaz, renderiza con la plataforma real (`app.platformName() == "windows"`) y
  usa `widget.grab()`; no necesita que la ventana sea visible. Los tests si usan offscreen.
- **Un dialogo modal cuelga pytest.** `tests/conftest.py` ya parchea `AnnotateTab._ask_discard`.
  Corre siempre `timeout 100 ./.venv/Scripts/python.exe -m pytest tests/ -q`. Si agregas otro dialogo
  modal, haz lo mismo.
- **La pantalla debe mostrar lo que se exporta.** El lienzo recorta lo dibujado al area exportada
  (imagen + margen). Una vez la pantalla prometia un resplandor que el PNG recortaba.
- **Qt degrada los enums `str, Enum`** a `str` al pasar por `currentData()`: envuelve con `Enum(...)`.
- **Parametros que chocan con campos**: `edit_selected(text=...)` fallo porque el parametro del metodo se
  llamaba igual que el campo. Por eso el flag es `_merge` (con guion bajo).
- **Granularidad del deshacer**: una decision = un paso. Los colores (dialogo modal) y los presets NO se
  fusionan; las ediciones solo se fusionan si son del MISMO campo (escribir texto, girar un spinbox).
- **Lambdas conectadas a senales** de un objeto que se destruye imprimen tracebacks; usa metodos
  enlazados (PySide los desconecta solos).
- **Aliasing de `self.config`** en `_apply_config_to_widgets` (pestana Portada): se asigna AL FINAL.
- `resvg_py` no libera el GIL (hilos no aceleran); no usar `cairosvg` (pide libcairo en Windows).
- Pillow 12.3 sin `raqm` no hace kerning: mide 0.2-0.5% de mas que resvg; Qt mide mejor (0.77 px de error
  medio). Pillow solo vale por no depender de Qt (hilo de export, CLI, tests).
- El README debe quedar en UTF-8 (estaba en UTF-16 y la herramienta de escritura lo conservaba).
- Las anotaciones nuevas tocan SIEMPRE los mismos sitios: `core/annotate/model.py` (dataclass +
  union `Annotation`), `primitives.py` (primitivas), `svg.py` (si hay primitiva nueva), `io.py`
  (serializar con `.get(...)` para que proyectos viejos abran), `edit.py` (hit-test/asas/mover),
  `ui/annotate/controller.py` (herramienta), `panel.py` (propiedades), `painter.py` (pantalla), `tab.py`
  (boton). Y sus tests en `tests/`.

## 5. Pendiente aparte (no mezclar con lo anterior)

**Animaciones, fases 1 a 7** — ver `docs/arquitectura-animacion.md` (tiene firmas, criterios de
aceptacion y riesgos). La siguiente es la fase 1: refactor de `build_svg` que debe dejar el PNG
byte-identico. El usuario decide cuando; no la empieces sin preguntar.

## 6. Prompt para pegar al iniciar la sesion

> Continuamos Cover Studio en `D:\repos\cover_studio`. Lee primero `docs/siguiente-sesion.md` (estado,
> preferencias, trampas y backlog) y luego `docs/arquitectura-anotar.md`. Corre `git status` y los tests.
> Vamos a trabajar el backlog de la pestana Anotar en este orden, UNA funcion a la vez, con tests y
> verificacion visual, y dandome el comando de commit despues de cada una (sin Co-Authored-By): 1) recortar
> captura, 2) resaltador con colores estandar de papeleria y personalizados, 3) zoom y desplazamiento del
> lienzo, 4) foco con modo oscurecer o desenfocar. Empieza por la 1: dime en pocas lineas tu plan y espera
> mi visto bueno antes de escribir codigo.
