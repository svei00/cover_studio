"""Geometria pura de los iconos (check, cruz, alerta...): contenedor y glifo en coordenadas UNITARIAS (el contenedor cabe en
un circulo de radio 1 centrado en el origen, y crece hacia abajo como en pantalla). Sin Qt ni Pillow: lo usan el pintor de
Qt y el exportador SVG a traves de las mismas primitivas, asi que se ven igual en pantalla y en el PNG."""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.annotate.model import IconKind

Point = tuple[float, float]


@dataclass(frozen=True)
class Glyph:
    """Trazos (polilineas de remate redondo) y puntos (centro, radio) del simbolo, en unidades del icono."""

    strokes: tuple[tuple[Point, ...], ...] = ()
    dots: tuple[tuple[Point, float], ...] = ()


def _hook() -> tuple[Point, ...]:
    """El gancho del signo de interrogacion: un arco por arriba que baja hacia el centro."""
    cx, cy, radius = 0.0, -0.22, 0.31
    arc = [(cx + radius * math.cos(math.radians(t)), cy - radius * math.sin(math.radians(t))) for t in range(165, -61, -15)]
    return tuple(arc) + ((0.0, 0.12),)


def _star() -> tuple[Point, ...]:
    points = []
    for i in range(10):
        radius = 0.98 if i % 2 == 0 else 0.42
        angle = math.radians(-90 + 36 * i)
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return tuple(points)


_TRIANGLE: tuple[Point, ...] = ((0.0, -0.90), (0.90, 0.66), (-0.90, 0.66))
_STAR = _star()

_GLYPHS: dict[IconKind, Glyph] = {
    IconKind.CHECK: Glyph(strokes=(((-0.40, 0.04), (-0.10, 0.34), (0.44, -0.30)),)),
    IconKind.CROSS: Glyph(strokes=(((-0.34, -0.34), (0.34, 0.34)), ((0.34, -0.34), (-0.34, 0.34)))),
    IconKind.PLUS: Glyph(strokes=(((-0.40, 0.0), (0.40, 0.0)), ((0.0, -0.40), (0.0, 0.40)))),
    IconKind.MINUS: Glyph(strokes=(((-0.40, 0.0), (0.40, 0.0)),)),
    IconKind.INFO: Glyph(strokes=(((0.0, -0.08), (0.0, 0.42)),), dots=(((0.0, -0.40), 0.10),)),
    IconKind.WARNING: Glyph(strokes=(((0.0, -0.20), (0.0, 0.20)),), dots=(((0.0, 0.45), 0.095),)),
    IconKind.QUESTION: Glyph(strokes=(_hook(),), dots=(((0.0, 0.42), 0.10),)),
    IconKind.STAR: Glyph(),   # la estrella es su propio contenedor
}

# Iconos cuyo contenedor NO es un circulo
_POLYGONS: dict[IconKind, tuple[Point, ...]] = {IconKind.WARNING: _TRIANGLE, IconKind.STAR: _STAR}


def glyph(kind: IconKind) -> Glyph:
    return _GLYPHS[kind]


def container_polygon(kind: IconKind) -> tuple[Point, ...] | None:
    """Vertices del contenedor (triangulo de la alerta, estrella) o None si es el circulo."""
    return _POLYGONS.get(kind)


def has_glyph(kind: IconKind) -> bool:
    return bool(_GLYPHS[kind].strokes or _GLYPHS[kind].dots)
