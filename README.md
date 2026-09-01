# Cover Studio

GUI de escritorio (PySide6) para generar portadas 16:9 de Excel Solutions:
una foto de fondo con una banda de color, un titulo y un acento en "L" que
la abraza.

## Instalacion

Requiere Python 3.11+ (probado con 3.14). Windows es el entorno principal.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Uso

```bash
.venv\Scripts\python main.py
```

1. Escribe el titulo y arrastra (o busca con "Examinar...") la foto de fondo.
2. Ajusta colores, geometria, tipografia y lienzo en el panel izquierdo. La
   vista previa de la derecha se actualiza sola medio segundo despues de
   cada cambio.
3. Arrastra la banda verde directamente en la vista previa para
   reposicionarla, o usa los sliders de margen para coordenadas exactas.
4. Click en **Generar**. La ruta de salida se autocompleta como
   `<carpeta-de-la-foto>/<slug-del-titulo>-cover.png`, editable.
5. Guarda combinaciones de diseno como preset desde la barra superior;
   `default.json` trae los valores de marca.

Si la ruta de salida coincide con la de la foto original, la app exige
escribir `SOBRESCRIBIR` para confirmar y guarda automaticamente una copia
`<archivo>.original.png` antes de sobrescribir.

## Pestaña "Anotar"

Anota capturas de pantalla con la identidad visual de Excel Solutions.

1. Abre una captura (**Abrir...**, arrastrándola a la ventana, o pegándola con `CTRL + V`;
   las pegadas se guardan en la carpeta Imágenes, subcarpeta Cover Studio).
2. Elige una herramienta y dibuja sobre la captura: **Marcador** (recuadro con
   resplandor dorado y flecha), **Flecha**, **Paso** (círculo numerado), **Texto**
   (etiqueta con presets de marca), **Pixelar** (para anonimizar RFC, nombres, UUID)
   y **Lupa** (amplía una zona en un lente aparte: circular, ovalada, o rectangular con
   esquinas ajustables). Hay **Marcador** (con flecha) y **Recuadro** (sin flecha).
3. **Seleccionar** mueve y redimensiona; `Suprimir` borra; `CTRL + Z` / `CTRL + Y`
   deshacen y rehacen. El panel de la derecha edita las propiedades de lo seleccionado
   y, sin selección, el margen extra y la escala de trazo del documento.
4. **Exportar PNG...** (y SVG opcional) o **Copiar** al portapapeles. Nunca sobrescribe
   la captura original salvo que escribas `SOBRESCRIBIR`, y entonces la respalda como
   `<nombre>.original.png`.
5. **Guardar proyecto** (`CTRL + S`) deja un `.anotar.json` junto a la captura; al
   volver a abrirla se recuperan las anotaciones.

**Colores:** por defecto son los de marca. Sin selección, el panel tiene la paleta del
documento (recuadro, flecha, resplandor, marco de la lupa, paso numerado) y
"Restaurar colores de marca"; cada anotación puede además tener un color propio y volver
a la paleta con el botón "Paleta". La paleta se guarda en el proyecto.

El pixelado se aplica antes que todo lo demás: un dato tapado no reaparece dentro de una
lupa ni en el SVG exportado. El diseño completo está en `docs/arquitectura-anotar.md`.

## Estructura

```
core/       logica pura (SVG, texto, presets) — sin Qt, testeable por separado
ui/         ventana, widgets reutilizables y panel de vista previa
presets/    presets guardados en JSON
tests/      pytest para core/
```

## Tests

```bash
.venv\Scripts\python -m pytest tests/ -v
```

## Notas tecnicas

- El SVG se rasteriza con `resvg_py` (bindings de Rust, sin dependencias
  nativas). No usa `cairosvg`: en Windows requiere instalar por separado el
  runtime de GTK para obtener `libcairo-2.dll`, algo que `resvg_py` evita
  por completo.
- El acento en "L" se deriva de un solo calculo con signos segun la
  orientacion (`compute_accent_path` en `core/geometry.py`), no de cuatro
  bloques copiados — asi las cuatro orientaciones quedan geometricamente
  consistentes y las esquinas redondeadas cierran bien en cualquier radio.
