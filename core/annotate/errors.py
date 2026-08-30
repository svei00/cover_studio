"""Errores del modulo de anotaciones. Heredan de GeometryError para que la UI,
que ya la captura, los muestre sin tracebacks."""

from __future__ import annotations

from core.geometry import GeometryError


class AnnotateError(GeometryError):
    """Error al cargar, anotar o exportar una captura."""
