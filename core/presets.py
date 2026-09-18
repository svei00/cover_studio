"""Guardar y cargar presets de diseno (colores, geometria, tipografia) en
JSON. El titulo y las rutas de foto/salida no forman parte del preset."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path

from core.geometry import (
    CanvasSize,
    CoverConfig,
    FontWeight,
    GradientDirection,
    Orientation,
    SubtitlePosition,
    VerticalPosition,
)


class PresetError(Exception):
    """Error leyendo o escribiendo un archivo de preset."""


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def config_to_dict(config: CoverConfig) -> dict:
    """Serializa un CoverConfig a un dict JSON-safe (enums y CanvasSize a valores planos)."""
    data = asdict(config)
    data["canvas"] = {"width": config.canvas.width, "height": config.canvas.height}
    data["orientation"] = config.orientation.value
    data["vertical_position"] = config.vertical_position.value
    data["font_weight"] = config.font_weight.value
    data["subtitle_position"] = config.subtitle_position.value
    data["subtitle_gradient_direction"] = config.subtitle_gradient_direction.value
    return data


def config_from_dict(data: dict) -> CoverConfig:
    """Reconstruye un CoverConfig desde un dict, ignorando claves desconocidas
    y usando los defaults de marca para lo que falte."""
    defaults = CoverConfig()
    canvas_data = data.get("canvas")
    canvas = CanvasSize(**canvas_data) if canvas_data else defaults.canvas

    valid_fields = {f.name for f in fields(CoverConfig)}
    kwargs = {key: value for key, value in data.items() if key in valid_fields and key != "canvas"}

    if "orientation" in kwargs:
        kwargs["orientation"] = Orientation(kwargs["orientation"])
    if "vertical_position" in kwargs:
        kwargs["vertical_position"] = VerticalPosition(kwargs["vertical_position"])
    if "font_weight" in kwargs:
        kwargs["font_weight"] = FontWeight(kwargs["font_weight"])
    for key in ("subtitle_x", "subtitle_y"):
        value = kwargs.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            kwargs["subtitle_x"] = kwargs["subtitle_y"] = None   # dato danado: posicion automatica
    if (kwargs.get("subtitle_x") is None) != (kwargs.get("subtitle_y") is None):
        kwargs["subtitle_x"] = kwargs["subtitle_y"] = None       # van juntas: si falta una, ninguna
    for key in ("subtitle_bg_color2", "subtitle_outline_color"):   # un color danado usa el de siempre
        if key in kwargs and not (isinstance(kwargs[key], str) and _HEX_RE.fullmatch(kwargs[key])):
            del kwargs[key]
    for key in ("subtitle_gradient", "subtitle_outline_enabled"):
        if key in kwargs and not isinstance(kwargs[key], bool):
            del kwargs[key]
    if "subtitle_gradient_direction" in kwargs:
        try:
            kwargs["subtitle_gradient_direction"] = GradientDirection(kwargs["subtitle_gradient_direction"])
        except ValueError:
            del kwargs["subtitle_gradient_direction"]
    if "subtitle_position" in kwargs:
        try:
            kwargs["subtitle_position"] = SubtitlePosition(kwargs["subtitle_position"])
        except ValueError:   # un valor desconocido usa el de siempre (abajo-derecha)
            del kwargs["subtitle_position"]

    return CoverConfig(canvas=canvas, **kwargs)


def save_preset(config: CoverConfig, name: str, presets_dir: Path) -> Path:
    """Guarda config como <presets_dir>/<name>.json. Devuelve la ruta escrita."""
    safe_name = name.strip()
    if not safe_name:
        raise PresetError("El preset necesita un nombre.")
    try:
        presets_dir.mkdir(parents=True, exist_ok=True)
        path = presets_dir / f"{safe_name}.json"
        path.write_text(json.dumps(config_to_dict(config), indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"No se pudo guardar el preset: {exc}") from exc
    return path


def load_preset(path: Path) -> CoverConfig:
    """Carga un CoverConfig desde un archivo JSON de preset."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetError(f"No se pudo leer el preset {path.name}: {exc}") from exc
    return config_from_dict(data)


def list_presets(presets_dir: Path) -> list[Path]:
    """Lista los archivos .json de presets disponibles, ordenados por nombre."""
    if not presets_dir.exists():
        return []
    return sorted(presets_dir.glob("*.json"))
