"""Orden de las capas (Traer al frente, Enviar atras...): logica pura, sin Qt.

El orden de `doc.items` ES el apilado: lo ultimo se dibuja encima. Pero no todo se apila entre si:
- las IMAGENES PEGADAS se componen en el bitmap y siempre quedan DEBAJO de las anotaciones: entre ellas hay orden, pero ninguna
  pasa por encima de una flecha, por mucho que se "traiga al frente";
- el pixelado y el foco se aplican al bitmap (no se apilan visualmente): no tienen orden que cambiar;
- todo lo demas (marcadores, flechas, texto, lupas...) forma la capa de anotaciones.
Cada grupo se reordena por separado, y el resultado vuelve a las mismas posiciones de la lista."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from enum import Enum

from core.annotate.model import Annotation, ImageOverlay, Redaction, Spotlight


class Order(str, Enum):
    FRONT = "front"          # encima de todo (de su grupo)
    BACK = "back"            # debajo de todo (de su grupo)
    FORWARD = "forward"      # un nivel hacia arriba
    BACKWARD = "backward"    # un nivel hacia abajo


def layer_of(item: Annotation) -> str | None:
    """'image' (imagenes pegadas), 'annotation' (lo dibujado encima) o None (pixelado y foco: sin orden visual)."""
    if isinstance(item, ImageOverlay):
        return "image"
    if isinstance(item, (Redaction, Spotlight)):
        return None
    return "annotation"


def _reorder_group(seq: list[Annotation], selected: Collection[str], mode: Order) -> list[Annotation]:
    chosen = [i for i in seq if i.id in selected]
    if not chosen or len(chosen) == len(seq):
        return seq                                            # nada seleccionado aqui, o ya es todo el grupo
    rest = [i for i in seq if i.id not in selected]
    if mode is Order.FRONT:
        return rest + chosen
    if mode is Order.BACK:
        return chosen + rest
    out = list(seq)
    if mode is Order.FORWARD:
        for i in range(len(out) - 2, -1, -1):                 # de arriba abajo: nadie se mueve dos veces
            if out[i].id in selected and out[i + 1].id not in selected:
                out[i], out[i + 1] = out[i + 1], out[i]
    else:
        for i in range(1, len(out)):
            if out[i].id in selected and out[i - 1].id not in selected:
                out[i], out[i - 1] = out[i - 1], out[i]
    return out


def reorder(items: Sequence[Annotation], selected: Collection[str], mode: Order) -> list[Annotation]:
    """La lista con las `selected` movidas segun `mode`, conservando entre ellas su orden relativo. Cada grupo (imagenes,
    anotaciones) se reordena por separado y devuelve sus elementos a las posiciones que ya ocupaba."""
    out = list(items)
    for layer in ("image", "annotation"):
        positions = [i for i, item in enumerate(out) if layer_of(item) == layer]
        group = [out[i] for i in positions]
        for position, item in zip(positions, _reorder_group(group, selected, mode)):
            out[position] = item
    return out


def can_reorder(items: Sequence[Annotation], selected: Collection[str], mode: Order) -> bool:
    """True si `mode` cambiaria algo (asi el menu deshabilita 'Traer al frente' en lo que ya esta arriba)."""
    return [i.id for i in reorder(items, selected, mode)] != [i.id for i in items]
