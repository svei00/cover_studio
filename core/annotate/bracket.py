"""Llave, corchete, parentesis y cota: la geometria (pura, sin Qt) de la anotacion `Bracket`.

Un `Bracket` va de `start` a `end` (el tramo que abarca, como una flecha) y tiene un PICO a `depth` px del tramo, hacia un lado u otro
(`flip`). Se calcula en coordenadas LOCALES (x a lo largo del tramo, de 0 a su largo L; y hacia afuera, de 0 en el tramo a `depth` en
el pico) y se lleva a la imagen con la direccion del tramo, asi funciona en cualquier angulo:

    llave `{`        dos arcos que suben a la mitad de la altura, corren paralelos al tramo y se juntan en un pico a `depth`
    corchete `[`     tres lados: sube, cruza a `depth` y baja (esquinas redondeadas)
    parentesis `(`   un arco (Bezier cuadratica) que pasa por el pico
    cota `|<->|`     dos lineas de extension y una linea a `depth` (las puntas las pone el dibujo)

El texto o el icono del pico se colocan fuera, pasando el pico (ver `primitives.bracket_tip_item`)."""

from __future__ import annotations

import math

from core.annotate import style
from core.annotate.model import Bracket, BracketKind

Point = tuple[float, float]

_ARC_STEPS = 10


def span(b: Bracket) -> tuple[Point, Point, float]:
    """(direccion unitaria del tramo, su normal 'izquierda', largo). Con start == end el largo es 0."""
    dx, dy = b.end[0] - b.start[0], b.end[1] - b.start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return (1.0, 0.0), (0.0, 1.0), 0.0
    u = (dx / length, dy / length)
    return u, (-u[1], u[0]), length


def side(b: Bracket) -> float:
    """+1 hacia la normal 'izquierda' del tramo; -1 con `flip`."""
    return -1.0 if b.flip else 1.0


def default_depth(start: Point, end: Point) -> float:
    """Altura del pico al dibujar una nueva: proporcional al largo, entre un minimo y un tope (una llave de 600 px no necesita 70 de
    alto, y una de 40 px tampoco 5)."""
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    return min(style.MAX_DEFAULT_BRACKET_DEPTH, max(style.MIN_DEFAULT_BRACKET_DEPTH, style.DEFAULT_BRACKET_DEPTH_RATIO * length))


def _world(b: Bracket, local: list[Point]) -> list[Point]:
    u, n, _length = span(b)
    s = side(b)
    return [(b.start[0] + u[0] * x + n[0] * s * y, b.start[1] + u[1] * x + n[1] * s * y) for x, y in local]


def tip_point(b: Bracket) -> Point | None:
    """El pico (o el medio de la barra en el corchete y la cota): donde va el asa de la profundidad. None si el tramo no mide nada."""
    u, n, length = span(b)
    if length == 0:
        return None
    return _world(b, [(length / 2, b.depth)])[0]


def outward(b: Bracket) -> Point:
    """Direccion unitaria en que apunta el pico (hacia donde se coloca el texto o el icono)."""
    _u, n, _length = span(b)
    s = side(b)
    return (n[0] * s, n[1] * s)


def _brace_local(length: float, depth: float) -> list[Point]:
    """La llave en locales: arcos de cuarto de elipse de x-radio `rx` y y-radio `depth / 2`, un tramo recto a esa altura, y un
    pico en el medio. Con un tramo corto `rx` se acota a L / 4 (la profundidad se conserva; los arcos solo se hacen mas angostos)."""
    ry = depth / 2
    rx = min(ry, length / 4)
    left: list[Point] = []
    for i in range(_ARC_STEPS + 1):                       # del extremo (0, 0) a (rx, ry)
        t = i / _ARC_STEPS * math.pi / 2
        left.append((rx - rx * math.cos(t), ry * math.sin(t)))
    cx, cy = length / 2 - rx, 2 * ry                      # del tramo recto hacia el pico (L / 2, depth)
    for i in range(_ARC_STEPS + 1):
        phi = -math.pi / 2 + i / _ARC_STEPS * math.pi / 2
        point = (cx + rx * math.cos(phi), cy + ry * math.sin(phi))
        if math.hypot(point[0] - left[-1][0], point[1] - left[-1][1]) > 1e-9:
            left.append(point)
    right = [(length - x, y) for x, y in reversed(left)]
    return left + right[1:]                               # el pico no se repite


def _round_corners(points: list[Point], radius: float) -> list[Point]:
    """Cambia cada vertice interior por un arco (Bezier cuadratica con el vertice de control) de hasta `radius`."""
    out = [points[0]]
    for prev, vertex, nxt in zip(points, points[1:], points[2:]):
        d0 = math.hypot(prev[0] - vertex[0], prev[1] - vertex[1])
        d1 = math.hypot(nxt[0] - vertex[0], nxt[1] - vertex[1])
        r = min(radius, d0 / 2, d1 / 2)
        if r < 0.5:
            out.append(vertex)
            continue
        a = (vertex[0] + (prev[0] - vertex[0]) / d0 * r, vertex[1] + (prev[1] - vertex[1]) / d0 * r)
        c = (vertex[0] + (nxt[0] - vertex[0]) / d1 * r, vertex[1] + (nxt[1] - vertex[1]) / d1 * r)
        for i in range(7):
            t = i / 6
            w = 1 - t
            out.append((w * w * a[0] + 2 * w * t * vertex[0] + t * t * c[0], w * w * a[1] + 2 * w * t * vertex[1] + t * t * c[1]))
    out.append(points[-1])
    return out


def _paren_local(length: float, depth: float) -> list[Point]:
    steps = min(60, max(12, int(length / 6)))
    out = []
    for i in range(steps + 1):
        t = i / steps
        w = 1 - t
        out.append((2 * w * t * (length / 2) + t * t * length, 2 * w * t * (2 * depth)))   # control (L / 2, 2 * depth): el pico queda a `depth`
    return out


def outline_paths(b: Bracket) -> list[list[Point]]:
    """Los trazos de la forma, en coordenadas de la imagen (cada uno una polilinea). Vacio si el tramo no mide nada. La cota lleva TRES
    (dos lineas de extension y la linea a `depth`); las demas formas, uno."""
    _u, _n, length = span(b)
    if length == 0:
        return []
    depth = max(style.MIN_BRACKET_DEPTH, b.depth)
    if b.kind is BracketKind.SQUARE:
        local = [_round_corners([(0.0, 0.0), (0.0, depth), (length, depth), (length, 0.0)], style.BRACKET_SQUARE_CORNER)]
    elif b.kind is BracketKind.PAREN:
        local = [_paren_local(length, depth)]
    elif b.kind is BracketKind.DIMENSION:
        over = depth + style.BRACKET_DIM_OVERSHOOT
        local = [[(0.0, 0.0), (0.0, over)], [(length, 0.0), (length, over)], [(0.0, depth), (length, depth)]]
    else:
        local = [_brace_local(length, depth)]
    return [_world(b, path) for path in local]


def measure(b: Bracket) -> int:
    """Lo que mide el tramo, en px de la captura (la medida de una cota sin texto propio)."""
    return round(span(b)[2])


def label_text(b: Bracket) -> str:
    """El texto del pico: el que se escribio; en una cota sin texto, su medida ('480 px'); en las demas, nada."""
    if b.label:
        return b.label
    return f"{measure(b)} px" if b.kind is BracketKind.DIMENSION else ""
