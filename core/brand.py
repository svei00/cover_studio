"""Colores de marca configurables. Un solo archivo `brand.json` en la carpeta de datos del USUARIO (junto a los
colores personalizados) con el nombre de la marca y sus colores con nombre. Alimenta los valores POR DEFECTO de las
dos pestanas:

- Portada: `default_cover_config()` es un `CoverConfig` con los colores de la marca (banda, acento, texto, contorno,
  subtitulo, y los segundos colores de los degradados del subtitulo).
- Anotar: `brand_palette()` es la `Palette` de los documentos NUEVOS y del boton "Restaurar colores de marca".

Sin archivo (o con uno danado) la marca es Excel Solutions, y esos valores son EXACTAMENTE los de siempre: nada cambia
hasta que alguien guarda su marca. Los proyectos de Anotar ya guardados llevan su paleta completa y no cambian.
Logica pura, sin Qt."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

from core.annotate.palette import BRAND_PALETTE, Palette
from core.geometry import CoverConfig
from core.user_settings import user_data_dir, write_text_atomic

BRAND_FILE = "brand.json"
DEFAULT_NAME = "Excel Solutions"
MAX_NAME_LENGTH = 60
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_BUILTIN_COVER = CoverConfig()


@dataclass(frozen=True)
class Brand:
    """Nombre y colores de la marca. Los valores por defecto son los de Excel Solutions."""

    name: str = DEFAULT_NAME
    # Portada
    band: str = _BUILTIN_COVER.band_color
    accent: str = _BUILTIN_COVER.accent_color
    text: str = _BUILTIN_COVER.text_color
    outline: str = _BUILTIN_COVER.text_outline_color
    subtitle_bg: str = _BUILTIN_COVER.subtitle_bg_color
    subtitle_border: str = _BUILTIN_COVER.subtitle_border_color
    # Anotar
    mark: str = BRAND_PALETTE.marker
    glow: str = BRAND_PALETTE.glow
    lens: str = BRAND_PALETTE.lens
    step: str = BRAND_PALETTE.step
    highlight: str = BRAND_PALETTE.highlight


# (clave, etiqueta) por grupo: el orden y los textos del dialogo
COVER_COLORS: tuple[tuple[str, str], ...] = (
    ("band", "Banda"),
    ("accent", "Acento"),
    ("text", "Texto"),
    ("outline", "Contorno del texto"),
    ("subtitle_bg", "Subtitulo: fondo"),
    ("subtitle_border", "Subtitulo: borde"),
)
ANNOTATE_COLORS: tuple[tuple[str, str], ...] = (
    ("mark", "Recuadro, flecha y lapiz"),
    ("glow", "Resplandor"),
    ("lens", "Marco de la lupa"),
    ("step", "Paso numerado"),
    ("highlight", "Resaltador"),
)
COLOR_KEYS = tuple(k for k, _ in COVER_COLORS + ANNOTATE_COLORS)

# a que campos del CoverConfig / de la Palette alimenta cada color de la marca
_COVER_TARGETS: dict[str, tuple[str, ...]] = {
    "band": ("band_color", "subtitle_border_color2"),       # el verde de la banda cierra el degradado del borde
    "accent": ("accent_color", "subtitle_bg_color2"),       # el azul de acento cierra el degradado del relleno
    "text": ("text_color", "subtitle_text_color"),
    "outline": ("text_outline_color", "subtitle_outline_color"),
    "subtitle_bg": ("subtitle_bg_color",),
    "subtitle_border": ("subtitle_border_color",),
}
_PALETTE_TARGETS: dict[str, tuple[str, ...]] = {
    "mark": ("marker", "arrow", "pen"),
    "glow": ("glow",),
    "lens": ("lens",),
    "step": ("step",),
    "highlight": ("highlight",),
}

DEFAULT_BRAND = Brand()


def is_valid_hex(value: object) -> bool:
    return isinstance(value, str) and _HEX_RE.fullmatch(value) is not None


def brand_path() -> Path:
    return user_data_dir() / BRAND_FILE


def normalize(brand: Brand) -> Brand:
    """Marca limpia: nombre sin espacios sobrantes (y acotado; vacio = el de siempre) y cada color como #RRGGBB en
    mayusculas (lo invalido vuelve al de Excel Solutions)."""
    name = brand.name.strip()[:MAX_NAME_LENGTH].strip() if isinstance(brand.name, str) else ""
    values = {
        key: (getattr(brand, key).upper() if is_valid_hex(getattr(brand, key)) else getattr(DEFAULT_BRAND, key))
        for key in COLOR_KEYS
    }
    return Brand(name=name or DEFAULT_NAME, **values)


def brand_to_dict(brand: Brand) -> dict:
    brand = normalize(brand)
    return {"version": 1, "name": brand.name, "colors": {key: getattr(brand, key) for key in COLOR_KEYS}}


def brand_from_dict(data: object) -> Brand:
    """Marca desde un dict; lo que falte o este danado usa el de Excel Solutions (nunca falla)."""
    if not isinstance(data, dict):
        return DEFAULT_BRAND
    colors = data.get("colors")
    colors = colors if isinstance(colors, dict) else {}
    valid = {f.name for f in fields(Brand)} - {"name"}
    kwargs = {k: v for k, v in colors.items() if k in valid and is_valid_hex(v)}
    name = data.get("name")
    if isinstance(name, str):
        kwargs["name"] = name
    return normalize(Brand(**kwargs))


_cache: tuple[Path, int, int, Brand] | None = None


def load_brand(path: Path | None = None) -> Brand:
    """La marca guardada, o Excel Solutions si no hay archivo o esta ilegible/danado. Se vuelve a leer solo si el
    archivo cambio (se consulta a menudo: el panel de Anotar la usa en cada seleccion)."""
    global _cache
    path = path or brand_path()
    try:
        stat = path.stat()
    except OSError:
        return DEFAULT_BRAND
    key = (path, stat.st_mtime_ns, stat.st_size)
    if _cache is not None and _cache[:3] == key:
        return _cache[3]
    try:
        brand = brand_from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        brand = DEFAULT_BRAND
    _cache = (*key, brand)
    return brand


def save_brand(brand: Brand, path: Path | None = None) -> Path:
    """Guarda la marca (normalizada) con escritura atomica. Falla con UserSettingsError si no se puede escribir."""
    global _cache
    path = path or brand_path()
    payload = json.dumps(brand_to_dict(brand), indent=2, ensure_ascii=False)
    write_text_atomic(path, payload, "los colores de marca")
    _cache = None
    return path


def cover_overrides(brand: Brand) -> dict[str, str]:
    """Campos del CoverConfig que fija la marca."""
    brand = normalize(brand)
    return {field: getattr(brand, key) for key, targets in _COVER_TARGETS.items() for field in targets}


def palette_overrides(brand: Brand) -> dict[str, str]:
    """Campos de la Palette de Anotar que fija la marca."""
    brand = normalize(brand)
    return {field: getattr(brand, key) for key, targets in _PALETTE_TARGETS.items() for field in targets}


def default_cover_config(brand: Brand | None = None) -> CoverConfig:
    """CoverConfig de partida con los colores de la marca (la guardada si no se da otra)."""
    return replace(CoverConfig(), **cover_overrides(brand or load_brand()))


def brand_palette(brand: Brand | None = None) -> Palette:
    """Palette de los documentos nuevos de Anotar con los colores de la marca (la guardada si no se da otra)."""
    return replace(BRAND_PALETTE, **palette_overrides(brand or load_brand()))
