"""Curvas de easing (ecuaciones de Penner, las mismas que usa GSAP). Matematica
pura, sin dependencias. Todas cumplen f(0) == 0 y f(1) == 1, y acotan la entrada
a [0, 1] para que un tiempo ligeramente fuera de rango no produzca valores raros."""

from __future__ import annotations

import math
from collections.abc import Callable
from enum import Enum

EasingFn = Callable[[float], float]

DEFAULT_OVERSHOOT = 1.0       # rebase de 3.7%: el "slight" de una animacion sutil (medido)
PENNER_OVERSHOOT = 1.70158    # el valor clasico de Penner/GSAP (rebase de 10%)


def clamp01(t: float) -> float:
    return min(1.0, max(0.0, t))


def lerp(a: float, b: float, t: float) -> float:
    """Interpolacion lineal entre a y b (t no se acota: lo decide quien llama)."""
    return a + (b - a) * t


def linear(t: float) -> float:
    return clamp01(t)


def ease_out_quad(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 2


def ease_out_cubic(t: float) -> float:
    """El default sensato: arranca rapido y asienta suave."""
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_out_quint(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 5


def ease_out_expo(t: float) -> float:
    t = clamp01(t)
    return 1.0 if t == 1.0 else 1.0 - 2.0 ** (-10.0 * t)


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 4.0 * t ** 3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def ease_out_back(t: float, overshoot: float = DEFAULT_OVERSHOOT) -> float:
    """Pasa de 1.0 y regresa. overshoot=0 equivale a ease_out_cubic. Rebase pico
    medido: 0.6 -> 1.25%, 1.0 -> 3.7%, 1.70158 -> 10%."""
    t = clamp01(t)
    if t == 0.0:
        return 0.0  # sin esto el punto flotante da -1.1e-16
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


def ease_out_elastic(t: float, amplitude: float = 1.0, period: float = 0.3) -> float:
    """Rebote elastico. Con los valores por defecto el pico es ~1.37."""
    t = clamp01(t)
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    a = max(amplitude, 1.0)
    s = period / (2.0 * math.pi) * math.asin(1.0 / a)
    return a * 2.0 ** (-10.0 * t) * math.sin((t - s) * 2.0 * math.pi / period) + 1.0


class Easing(str, Enum):
    LINEAR = "linear"
    OUT_QUAD = "out-quad"
    OUT_CUBIC = "out-cubic"
    OUT_QUINT = "out-quint"
    OUT_EXPO = "out-expo"
    IN_OUT_CUBIC = "in-out-cubic"
    OUT_BACK = "out-back"
    OUT_ELASTIC = "out-elastic"


EASING_BY_NAME: dict[Easing, EasingFn] = {
    Easing.LINEAR: linear,
    Easing.OUT_QUAD: ease_out_quad,
    Easing.OUT_CUBIC: ease_out_cubic,
    Easing.OUT_QUINT: ease_out_quint,
    Easing.OUT_EXPO: ease_out_expo,
    Easing.IN_OUT_CUBIC: ease_in_out_cubic,
    Easing.OUT_BACK: ease_out_back,
    Easing.OUT_ELASTIC: ease_out_elastic,
}


def get_easing(name: Easing | str) -> EasingFn:
    """Resuelve un nombre (o un Easing) a su funcion. ValueError si no existe."""
    try:
        return EASING_BY_NAME[Easing(name)]
    except ValueError:
        valid = ", ".join(e.value for e in Easing)
        raise ValueError(f"Easing desconocido: {name!r}. Opciones: {valid}") from None
