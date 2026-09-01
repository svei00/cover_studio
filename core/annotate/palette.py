"""Paleta de colores de las anotaciones. Los valores por defecto son los de marca de
Excel Solutions (los de infographic_builder.py); cada documento puede cambiarlos, y cada
anotacion puede sobreescribir el suyo (None = usa el de la paleta).

Es un modulo aparte, sin Qt, para que a futuro la paleta se pueda guardar y cargar como
preset igual que los de diseno de la pestana Portada."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields

from core.annotate import style

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_valid_hex(value: object) -> bool:
    """True si es un color #RRGGBB (lo que devuelve QColor.name())."""
    return isinstance(value, str) and _HEX_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class Palette:
    marker: str = style.RED          # recuadro del marcador
    arrow: str = style.RED           # flechas (la del marcador y la flecha suelta)
    glow: str = style.GLOW_GOLD      # resplandor del marcador y de las flechas
    lens: str = style.TAN            # marco, contorno punteado y conector de la lupa
    step: str = style.GOLD           # circulo y numero de los pasos


BRAND_PALETTE = Palette()

PALETTE_LABELS: dict[str, str] = {
    "marker": "Recuadro",
    "arrow": "Flecha",
    "glow": "Resplandor",
    "lens": "Marco de la lupa",
    "step": "Paso numerado",
}


def palette_to_dict(palette: Palette) -> dict[str, str]:
    return asdict(palette)


def palette_from_dict(data: object) -> Palette:
    """Reconstruye una Palette; lo que falte o no sea un #RRGGBB valido usa el de marca
    (asi un proyecto viejo, sin paleta, o con un dato dañado, se abre igual)."""
    if not isinstance(data, dict):
        return BRAND_PALETTE
    valid = {f.name for f in fields(Palette)}
    return Palette(**{k: v for k, v in data.items() if k in valid and is_valid_hex(v)})
