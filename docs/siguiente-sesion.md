# Traspaso para la siguiente sesion

Leelo completo antes de tocar codigo. Lo escribio la sesion anterior para que esta pueda empezar
sin repetir descubrimientos ni preguntar lo que ya se decidio. (Reescrito el 2026-10-18: el traspaso
anterior estaba desactualizado; todo su backlog esta HECHO.)

## 1. Que hay (estado al cerrar la sesion anterior)

Cover Studio: app de escritorio PySide6 en `D:\repos\cover_studio` (Windows, Python 3.14, venv en
`.venv`). Se abre con `run_cover_studio.bat` o `.vbs`. **1453 tests pasan.** Arbol limpio y todo subido:
el ultimo commit es `01951c6` (Escalar + colores de marca); antes `458a13e` (lapiz UI + Foco) y `fe2374d`
(nucleo del lapiz).

- **Pestana "Portada"**: genera portadas 16:9 (foto + banda + titulo + acento en L), vista previa en
  vivo con hilo y debounce, arrastre de la banda y del subtitulo, presets, guarda anti-sobrescritura.
  Subtitulo con degradado de relleno y de borde (dos colores), contorno de letras y posicion en pixeles.
  **Boton "Nueva portada"** (Ctrl+N, barra de arriba): `MainWindow.new_cover()` limpia titulo, subtitulo, foto, ruta de
  salida (y `output_manually_edited`, que si no frenaba el autorrelleno), `last_output_path`, el aviso de que no cabe y la
  vista previa (`PreviewWidget.clear_preview()` descarta tambien el render en curso). CONSERVA el diseno. Pregunta antes de
  descartar solo si hay contenido distinto de lo ultimo generado (`_cover_signature`). Tests: `tests/test_main_window_new_cover.py`.
  Nota de pruebas: `QTest.qWait` retiene el GIL y hace que el hilo de la vista previa tarde segundos; con `app.exec()` real tarda 0,5 s.
- **Pestana "Anotar"**: anota capturas con la identidad de Excel Solutions. Herramientas: Seleccionar,
  Marcador (con flecha), Recuadro, Resaltar, Flecha, Linea (puntas y estilos opcionales), **Lapiz** y
  **Resaltador libre** (mano alzada, suavizado), Paso, Texto, Pixelar, **Foco**, Lupa (rectangular por
  defecto; circular, ovalada o con esquinas; marco, conector y resplandor), Recortar (no destructivo).
  Todas se repiten sin volver a pulsar el boton MENOS Texto, Seleccionar, Recortar y Foco (`STICKY_TOOLS`).
  Paleta del documento + color propio por anotacion, margen extra, escala de trazo, deshacer/rehacer,
  restablecer al valor por defecto (doble clic en la etiqueta o boton), zoom/desplazamiento, guardar
  proyecto (`.anotar.json`), copiar, exportar PNG/SVG, aviso de cambios sin guardar.
- **Boton "Escalar"** (Anotar): agranda la captura ORIGINAL 2x/3x/4x (Lanczos + nitidez) y la guarda como
  `nombre@2x.png` aparte, sin tocar el documento abierto. Es solo remuestreo: no inventa detalle (Lightshot y
  la captura de Windows del usuario tienen la MISMA resolucion). La fase 2 con IA (Real-ESRGAN) NO esta hecha y
  no se recomienda para capturas con cifras (puede deformar digitos).
- **Colores de marca configurables**: `brand.json` en la carpeta de usuario (`%APPDATA%\Cover Studio`)
  alimenta los valores POR DEFECTO de Portada y de los documentos nuevos de Anotar. Boton "Editar colores de
  marca..." en las dos pestanas. Sin archivo = Excel Solutions identico a lo de siempre. NO cambia proyectos
  ya guardados ni presets.
- **Animaciones**: SOLO la fase 0 (`core/easing.py`, `core/text_metrics.py`). Fases 1 a 7 pendientes.

Mapa de modulos nuevos de esta etapa (todo con tests en `tests/`):
- `core/annotate/freehand.py` (lapiz: decimar -> suavizar Chaikin -> Ramer-Douglas-Peucker; curva Catmull-Rom
  compartida por Qt y SVG via `PPolyline`).
- `core/annotate/raster.py` (`apply_redactions`, `apply_spotlight`, `lens_crops`; orden del pipeline:
  captura -> pixelado -> recortes de lupa -> foco -> anotaciones).
- `core/annotate/upscale.py`, `core/brand.py`, `core/user_settings.py` (colores personalizados + escritura
  atomica `write_text_atomic`), `ui/brand_dialog.py`.

Documentos de diseno (fuente de verdad, leelos segun la tarea):
- `docs/arquitectura-anotar.md` — como esta hecha la pestana Anotar y por que (una seccion por funcion).
- `docs/arquitectura-animacion.md` — diseno de las animaciones (video/GIF), con firmas y criterios.

Al empezar: corre `git status` y `git log --oneline -5`, y la suite completa.

## 2. Como trabajar con este usuario

- Habla espanol. Directo, sin rodeos; reporta con honestidad lo que NO pudo probar y lo que encontraste
  mal (varias veces se encontraron fallos propios midiendo: un rendimiento de 54 s, una regresion de ancho
  de ventana, pruebas debiles).
- **Fases chicas y revisables.** Su limite semanal es real: no lances subagentes caros sin avisar.
  Prefiere Opus para arquitectura y Sonnet para ejecutar.
- **Commits: no los hagas tu** (salvo que el pida otra cosa, como la correccion del commit del TRUNC, que
  si autorizo explicitamente, incluido el force push). Dale los comandos en bloques ```bash``` separados.
  Mensaje en ingles o espanol claro, **sin Co-Authored-By** (lo pidio explicitamente). **Despues de que el
  diga que commiteo, VERIFICA con `git status` y `git show --stat HEAD`**: dos veces no habia commiteado (o el
  commit cayo en otro lado / llevaba otro mensaje); una vez un commit de otra sesion (mensaje de TRUNC) arrastro
  archivos del lapiz.
- Verifica con tests Y mirando el resultado en la ventana REAL (ver trampas). Si algo se puede medir, mide.
- No repitas lo ya decidido ni vuelvas a ofrecer opciones que descarto.

## 3. Pendiente: lo que el usuario pidio y aun NO esta hecho

### 3.1 Intensidad y grosor del Resplandor: HECHO (sin commitear al escribir esto)
Ver `docs/arquitectura-anotar.md` ("Resplandor ajustable"). Campos `glow_strength`/`glow_size` en las 5 anotaciones con
resplandor, helper `style.glow_rings`, filas en el panel. Tests: `tests/test_annotate_glow_tuning.py` y `_ui.py`.
Verificado a ojo sobre fondo claro y oscuro.

### 3.1b Conector de la lupa movible: HECHO (sin commitear al escribir esto)
Ver `docs/arquitectura-anotar.md` ("Conector de la lupa"). Tests: `tests/test_annotate_lens_connector_edit.py`.
El CODO en angulo recto tambien esta hecho (`connector_route`, `PPath`; `tests/test_annotate_lens_connector_elbow.py`).

### 3.1c Iconos vectoriales (check, cruz, alerta, info, pregunta, estrella, mas, menos): HECHO (fase A)
Ver `docs/arquitectura-anotar.md` ("Iconos vectoriales"). Botones Check / Cruz / Icono(menu). Tests: `test_annotate_icons.py`,
`test_annotate_icons_ui.py`. **Fase B pendiente (Svei la quiere despues):** emojis de Windows como stickers (boton que abre
Win+. o selector propio; Qt rasteriza el glifo a color con Segoe UI Emoji; se incrusta como imagen; el proyecto guarda el
caracter). Antes de prometerla, MEDIR que Qt los dibuje a color con ese metodo (hoy Texto los pinta monocromos en pantalla).

### 3.1d Seleccion multiple + alinear y distribuir: HECHO
Ver `docs/arquitectura-anotar.md` ("Seleccion multiple, alinear y distribuir"). Tests: `test_annotate_multiselect.py`,
`test_annotate_align.py`. **`selected_item()` es None con 2+ seleccionadas**: todo lo que edita propiedades es de una sola.

### 3.1e Pegar encima (Ctrl+Shift+V): FASES 1 Y 2 HECHAS
Ver `docs/arquitectura-anotar.md` ("Pegar encima" y "Menu de clic derecho y orden de las capas"). Tests: `test_annotate_overlay.py`,
`test_annotate_overlay_ui.py`, `test_annotate_layers.py`. Fase 1 commiteada (`77736a0`); la fase 2 (menu de clic derecho, Traer al
frente / Enviar atras, botones en el panel) esta hecha y SIN commitear al escribir esto.
**Pendiente, ya decidido con el usuario (2026-10-25):**
- **Fase 3** (confirmar con el usuario si entra): "Nuevo lienzo en blanco" (p. ej. 1920x1080 o del tamano del portapapeles) para armar
  composiciones con varias capturas; la captura base seria un PNG blanco generado.
- **La sombra se recorta en el borde de la captura** (el "Margen extra" no la deja salir). Se le dijo al usuario que si; ya se le corrigio
  en la sesion, pero falta implementar la composicion sobre un lienzo ampliado si la quiere.
- Atajos de teclado para el orden (Ctrl+] / Ctrl+[) y un menu en el hueco (Pegar encima): no pedidos.
- Fase B de iconos (emojis como stickers) puede reutilizar `ImageOverlay`.
- **Trampa de pruebas nueva**: un `QMenu.exec` real cuelga pytest y `monkeypatch` sobre `QMenu.exec` no lo intercepta; usa el punto
  `AnnotateCanvas._exec_menu` (conftest lo anula).

### 3.2 Otros (no pedidos; solo si el usuario los retoma)
- Escalado fase 2 (IA, Real-ESRGAN ncnn externo): no recomendado; ver arriba.
- Que un Paso nuevo herede el estilo del ultimo Paso; asas de tamano en el lienzo para el Paso.
- La marca no cubre tipografia ni algunos colores internos (presets de texto de Anotar, resaltador rapido): se
  agregarian como colores con nombre en `core/brand.py::Brand`.
- El color de marca del lapiz/flecha/recuadro (`#621132`, vino) casi no se ve sobre capturas OSCURAS: se cambia
  el color del trazo o se ajusta la marca.

## 4. Trampas tecnicas (cada una costo tiempo)

- **Herramienta Bash**: los heredocs con comillas triples simples o con ciertos caracteres hacen que el analizador
  del comando falle ("unexpected EOF"), y los escapes `\n` dentro de un heredoc de Python se convierten en
  saltos de linea reales. Escribe los scripts de parche con la herramienta Write en el scratchpad y ejecutalos.
  Los parches usan una funcion `patch(path, pairs)` que verifica `count == 1` y solo escribe si TODOS los
  reemplazos coinciden (si falla, no deja cambios a medias). Escribe siempre con `encoding="utf-8"`.
- **`QT_QPA_PLATFORM=offscreen` en Windows no tiene fuentes**: el texto sale como cuadritos. Para MIRAR la
  interfaz, renderiza con la plataforma real y usa `widget.grab()`; los tests si usan offscreen.
  **Los scripts visuales deben poner `COVER_STUDIO_HOME` a una carpeta temporal** (si no, escribirian el
  `brand.json` y los colores personalizados REALES del usuario). `tests/conftest.py` ya lo hace para los tests.
- **Un dialogo modal cuelga pytest.** `tests/conftest.py` parchea `AnnotateTab._ask_discard`. Corre siempre
  `timeout 118 ./.venv/Scripts/python.exe -m pytest tests -q`. En pruebas de dialogos, parchea `exec`.
- **La barra superior de Anotar esta AL LIMITE de ancho** (minimo de la pestana ~1264 px; pantallas de 1366 px).
  Agregar un boton la ensancho a 1408 y rompio un test de zoom y las ventanas chicas; la solucion fue que la
  etiqueta de informacion ceda (`QSizePolicy.Ignored`). Hay un test (`test_la_barra_superior_no_obliga...`).
- **La pantalla debe mostrar lo que se exporta**: el lienzo recorta lo dibujado al area exportada (imagen + margen).
- **Una sola geometria para pantalla y SVG**: `primitives.py` alimenta a Qt (`painter.py`) y a resvg (`svg.py`);
  cualquier primitiva nueva necesita pintor Qt, SVG, `bounds.py` y un test de paridad de pixeles.
- **Rendimiento**: mide las rutas con entradas patologicas (un trazo de 20000 puntos en zigzag tardaba 54 s antes de
  `decimate`).
- **Qt degrada los enums `str, Enum`** a `str` al pasar por `currentData()`: envuelve con `Enum(...)`.
- **Parametros que chocan con campos**: por eso el flag de `edit_selected` es `_merge`.
- **Granularidad del deshacer**: una decision = un paso (un trazo, un cambio de modo, reemplazar el foco = un paso;
  macro `beginMacro/endMacro` cuando hay varios comandos).
- **Lambdas conectadas a senales** de un objeto que se destruye imprimen tracebacks; usa metodos enlazados.
- **`self.config` en `_apply_config_to_widgets`** (Portada): se asigna AL FINAL. `font_family` de la ventana depende
  de las fuentes instaladas: no compares un `CoverConfig` completo, compara los campos de color.
- `resvg_py` no libera el GIL; no usar `cairosvg`. Pillow sin `raqm` no hace kerning.
- Las anotaciones nuevas tocan SIEMPRE los mismos sitios: `core/annotate/model.py` (dataclass + union), `style.py`
  (constantes), `primitives.py`, `bounds.py`, `svg.py`, `painter.py`, `io.py` (serializar con `.get(...)` y
  recortes de rango para que proyectos viejos abran), `edit.py` (hit-test/asas/mover/redimensionar),
  `ui/annotate/controller.py` (herramienta), `panel.py` (pagina de propiedades, indice `_PAGE_*` + rama en `sync`),
  `tab.py` (boton) y sus tests. Las del bitmap (pixelado, foco) ademas tocan `raster.py` y el pipeline de
  `tab.refresh` / `svg.build_svg`.
- **Atajos de Anotar (Ctrl+V/C/Z/Y/S/0/1/+/-)**: son `Qt.WindowShortcut`, NO `WidgetWithChildrenShortcut`. Con el segundo, al cambiar de
  pestana con el mouse el foco se queda en la `QTabBar` (fuera de la pestana) y Ctrl+V no hacia nada (bug reportado el 2026-10-22).
  Qt solo activa un atajo de ventana mientras su widget esta visible, asi que no choca con la pestana Portada; los cuadros de texto
  aceptan Copiar/Pegar/Deshacer por su cuenta (`ShortcutOverride`). Prueba: `tests/test_annotate_shortcuts.py`.
  `QTest.keyClick(w, ...)` manda la tecla a `w`, no al widget con foco: para probar un cuadro de texto apunta al cuadro.
- Git en Windows avisa "LF will be replaced by CRLF": es solo un aviso.

## 5. Pendiente aparte (no mezclar con lo anterior)

**Animaciones, fases 1 a 7** — ver `docs/arquitectura-animacion.md` (tiene firmas, criterios de
aceptacion y riesgos). La siguiente es la fase 1: refactor de `build_svg` que debe dejar el PNG
byte-identico. El usuario decide cuando; no la empieces sin preguntar.

## 6. Prompt para pegar al iniciar la sesion

> Continuamos Cover Studio en `D:\repos\cover_studio`. Lee primero `docs/siguiente-sesion.md` (estado,
> preferencias, trampas y pendiente) y luego la seccion relevante de `docs/arquitectura-anotar.md`. Corre
> `git status`, `git log --oneline -5` y la suite de tests. Lo siguiente es la seccion 3.1: poder cambiar la
> INTENSIDAD y el GROSOR del Resplandor de las anotaciones (marcador, flecha, paso, lupa y conector, lapiz).
> Confirma en una linea que "grosor" es el alcance del halo, dime tu plan en pocas lineas y espera mi visto
> bueno antes de escribir codigo. Trabaja en fases chicas, con tests y verificacion visual en la ventana
> real, y dame los comandos de commit (sin Co-Authored-By); despues de que commitee, verifica con git.
