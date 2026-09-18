"""Preferencias del usuario que deben sobrevivir entre sesiones (hoy: los "colores personalizados" del
selector de color). Logica pura, sin Qt.

Se guardan en la carpeta de datos del USUARIO, no dentro del proyecto: son suyas, no del repositorio, y asi
sobreviven a actualizar o reinstalar la app. En Windows: `%APPDATA%\\Cover Studio`; en otros sistemas
`$XDG_CONFIG_HOME/cover-studio` (o `~/.config/cover-studio`). La variable de entorno `COVER_STUDIO_HOME`
cambia la carpeta (para pruebas o para llevar la app en una memoria USB)."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

CUSTOM_COLORS_FILE = "custom_colors.json"
MAX_CUSTOM_COLORS = 16   # los espacios de "colores personalizados" del selector de color de Qt
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class UserSettingsError(Exception):
    """No se pudo leer o escribir un archivo de preferencias."""


def user_data_dir() -> Path:
    """Carpeta de datos del usuario para Cover Studio (no se crea hasta que se guarda algo)."""
    override = os.environ.get("COVER_STUDIO_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Cover Studio"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "cover-studio"


def custom_colors_path() -> Path:
    return user_data_dir() / CUSTOM_COLORS_FILE


def load_custom_colors(path: Path | None = None) -> list[str | None]:
    """Los colores personalizados guardados, siempre como una lista de `MAX_CUSTOM_COLORS` entradas
    (`#rrggbb` en minusculas o None en los espacios vacios o invalidos). Sin archivo, o con un archivo
    ilegible o danado, devuelve todo vacio: nunca falla, asi un JSON roto no impide abrir la app."""
    empty: list[str | None] = [None] * MAX_CUSTOM_COLORS
    path = path or custom_colors_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    colors = data.get("custom_colors") if isinstance(data, dict) else None
    if not isinstance(colors, list):
        return empty
    result: list[str | None] = []
    for value in colors[:MAX_CUSTOM_COLORS]:
        result.append(value.lower() if isinstance(value, str) and _HEX_RE.fullmatch(value) else None)
    return result + [None] * (MAX_CUSTOM_COLORS - len(result))


def save_custom_colors(colors: Sequence[str | None], path: Path | None = None) -> Path:
    """Guarda los colores personalizados (hasta `MAX_CUSTOM_COLORS`). Escribe a un archivo temporal y lo
    renombra, asi un corte a mitad de escritura no deja el JSON a medias."""
    path = path or custom_colors_path()
    clean = [c.lower() if isinstance(c, str) and _HEX_RE.fullmatch(c) else None for c in list(colors)[:MAX_CUSTOM_COLORS]]
    clean += [None] * (MAX_CUSTOM_COLORS - len(clean))
    payload = json.dumps({"version": 1, "custom_colors": clean}, indent=2, ensure_ascii=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise UserSettingsError(f"No se pudieron guardar los colores personalizados en {path}: {exc}") from exc
    return path
