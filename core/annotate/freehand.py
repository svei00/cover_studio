"""Trazos a mano alzada: de los puntos crudos del mouse a una curva limpia y ligera. Sin Qt.

Tuberia al soltar el mouse: puntos crudos -> suavizado (corta esquinas, quita el temblor) -> simplificacion
(Ramer-Douglas-Peucker, quita puntos que no aportan) -> se guardan POCOS puntos de control. Al dibujar, `flatten`
une esos puntos con una curva Catmull-Rom centripeta y devuelve la polilinea que usan, igual, el pintor de Qt y el
SVG (una sola geometria, dos rasterizadores)."""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

MIN_POINT_SPACING = 1.0     # al dibujar se ignoran los puntos a menos de esta distancia (px de la imagen)
SIMPLIFY_TOLERANCE = 0.8    # RDP: cuanto puede apartarse la curva simplificada de la suavizada (px de la imagen)
SMOOTH_PASSES = 2           # pasadas de corte de esquinas (Chaikin)
SAMPLE_SPACING = 2.5        # separacion aproximada de las muestras de la curva al dibujarla (px de la imagen)
MAX_POINTS = 5000           # tope de puntos de un trazo (un proyecto no debe crecer sin limite)
MAX_RAW_POINTS = 1500       # tope de puntos crudos al procesar: un garabato larguisimo no debe congelar la ventana
MIN_STROKE_LENGTH = 3.0     # un trazo mas corto que esto (un clic, un temblor) no se crea


def path_length(points: Sequence[Point]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def should_add(points: Sequence[Point], new: Point, spacing: float = MIN_POINT_SPACING) -> bool:
    """True si `new` esta lo bastante lejos del ultimo punto como para agregarlo al trazo en curso."""
    return not points or math.dist(points[-1], new) >= spacing


def decimate(points: Sequence[Point], limit: int) -> list[Point]:
    """Si hay mas de `limit` puntos, se queda con unos cuantos repartidos parejo (siempre el primero y el ultimo)."""
    n = len(points)
    if n <= limit or limit < 2:
        return list(points)
    step = (n - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


def smooth(points: Sequence[Point], passes: int = SMOOTH_PASSES) -> list[Point]:
    """Corta esquinas (Chaikin): cada segmento se reemplaza por dos puntos a 1/4 y 3/4. Conserva el primer y el
    ultimo punto (el trazo empieza y termina donde el usuario puso el mouse) y quita el temblor de la mano."""
    result = list(points)
    for _ in range(passes):
        if len(result) < 3:
            break
        nxt = [result[0]]
        for a, b in zip(result, result[1:]):
            nxt.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            nxt.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        nxt.append(result[-1])
        result = nxt
    return result


def _distance_to_segment(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def simplify(points: Sequence[Point], tolerance: float = SIMPLIFY_TOLERANCE) -> list[Point]:
    """Ramer-Douglas-Peucker, iterativo (un trazo largo no agota la recursion): deja solo los puntos que se
    apartan mas de `tolerance` de la recta que une a sus vecinos."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        worst, index = 0.0, -1
        for i in range(start + 1, end):
            d = _distance_to_segment(points[i], points[start], points[end])
            if d > worst:
                worst, index = d, i
        if index != -1 and worst > tolerance:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [p for p, k in zip(points, keep) if k]


def process(raw: Sequence[Point], tolerance: float = SIMPLIFY_TOLERANCE) -> tuple[Point, ...]:
    """Puntos crudos del mouse -> puntos de control del trazo (suavizados y simplificados), redondeados a
    centesimas de pixel (lo que se guarda en el proyecto)."""
    raw = decimate(raw, MAX_RAW_POINTS)
    if len(raw) < 3:
        cleaned = list(raw)
    else:
        cleaned = simplify(smooth(raw), tolerance)
    return tuple((round(x, 2), round(y, 2)) for x, y in cleaned[:MAX_POINTS])


def _knot(t: float, a: Point, b: Point) -> float:
    return t + max(math.dist(a, b), 1e-9) ** 0.5   # parametrizacion centripeta (alfa = 0.5): sin lazos ni picos


def flatten(points: Sequence[Point], spacing: float = SAMPLE_SPACING) -> list[Point]:
    """Polilinea de la curva que pasa por los puntos de control (Catmull-Rom centripeta), con una muestra cada
    `spacing` px. Con 1 o 2 puntos devuelve los mismos (un punto es un punto, dos son una recta)."""
    pts = list(points)
    if len(pts) < 3:
        return pts
    ext = [(2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1]), *pts,
           (2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1])]
    out: list[Point] = [pts[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = _knot(t0, p0, p1)
        t2 = _knot(t1, p1, p2)
        t3 = _knot(t2, p2, p3)
        steps = max(1, math.ceil(math.dist(p1, p2) / spacing))
        for s in range(1, steps + 1):
            t = t1 + (t2 - t1) * s / steps
            a1 = _lerp(p0, p1, (t - t0) / (t1 - t0), (t1 - t) / (t1 - t0))
            a2 = _lerp(p1, p2, (t - t1) / (t2 - t1), (t2 - t) / (t2 - t1))
            a3 = _lerp(p2, p3, (t - t2) / (t3 - t2), (t3 - t) / (t3 - t2))
            b1 = _lerp(a1, a2, (t - t0) / (t2 - t0), (t2 - t) / (t2 - t0))
            b2 = _lerp(a2, a3, (t - t1) / (t3 - t1), (t3 - t) / (t3 - t1))
            out.append(_lerp(b1, b2, (t - t1) / (t2 - t1), (t2 - t) / (t2 - t1)))
    return out


def _lerp(a: Point, b: Point, wb: float, wa: float) -> Point:
    return a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb


def bounding_box(points: Sequence[Point]) -> tuple[float, float, float, float]:
    """(x, y, ancho, alto) de los puntos."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def distance_to_polyline(p: Point, points: Sequence[Point]) -> float:
    """Distancia minima del punto a la polilinea (a un punto suelto si el trazo es uno solo)."""
    if not points:
        return math.inf
    if len(points) == 1:
        return math.dist(p, points[0])
    return min(_distance_to_segment(p, points[i], points[i + 1]) for i in range(len(points) - 1))
