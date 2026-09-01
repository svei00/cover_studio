"""Guardar y cargar el proyecto de anotaciones como JSON junto a la captura
(captura.png -> captura.anotar.json), para poder reabrir y corregir."""

from __future__ import annotations

import json
from pathlib import Path

from core.annotate.errors import AnnotateError
from core.annotate.palette import is_valid_hex, palette_from_dict, palette_to_dict
from core.annotate.style import DEFAULT_LENS_CORNER
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowSide,
    LensShape,
    Magnifier,
    Marker,
    Rect,
    Redaction,
    StepBadge,
    TextAlign,
    TextLabel,
)

SIDECAR_VERSION = 1


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}.anotar.json")


def _rect_to_list(r: Rect) -> list[float]:
    return [r.x, r.y, r.w, r.h]


def _corner_or_default(value: object) -> float:
    """Esquinas del lente: un numero entre 0 y 0.5; cualquier otra cosa usa el valor por defecto."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 0.5:
        return float(value)
    return DEFAULT_LENS_CORNER


def _color_or_none(value: object) -> str | None:
    """Color propio de una anotacion; un dato invalido cuenta como "usa la paleta"."""
    return value if is_valid_hex(value) else None


def item_to_dict(item: Annotation) -> dict:
    if isinstance(item, Marker):
        return {"type": "marker", "id": item.id, "rect": _rect_to_list(item.rect),
                "arrow": item.arrow.value, "glow": item.glow, "stroke_color": item.stroke_color,
                "glow_color": item.glow_color, "arrow_color": item.arrow_color}
    if isinstance(item, Arrow):
        return {"type": "arrow", "id": item.id, "start": list(item.start),
                "end": list(item.end), "glow": item.glow, "color": item.color,
                "glow_color": item.glow_color}
    if isinstance(item, StepBadge):
        return {"type": "step", "id": item.id, "center": list(item.center), "number": item.number,
                "color": item.color}
    if isinstance(item, TextLabel):
        return {"type": "text", "id": item.id, "pos": list(item.pos), "text": item.text,
                "size": item.size, "color": item.color, "bold": item.bold, "bg": item.bg,
                "bg_opacity": item.bg_opacity, "border": item.border,
                "border_width": item.border_width, "padding": item.padding, "rx": item.rx,
                "align": item.align.value, "outline": item.outline}
    if isinstance(item, Redaction):
        return {"type": "redaction", "id": item.id, "rect": _rect_to_list(item.rect), "block": item.block}
    if isinstance(item, Magnifier):
        return {"type": "magnifier", "id": item.id, "source": _rect_to_list(item.source),
                "lens_center": list(item.lens_center), "zoom": item.zoom,
                "shape": item.shape.value, "connector": item.connector, "frame_color": item.frame_color,
                "corner": item.corner}
    raise AnnotateError(f"Anotacion desconocida: {type(item).__name__}")


def item_from_dict(data: dict) -> Annotation:
    kind = data.get("type")
    try:
        if kind == "marker":
            return Marker(
                data["id"], Rect(*data["rect"]), ArrowSide(data["arrow"]), data["glow"],
                _color_or_none(data.get("stroke_color")), _color_or_none(data.get("glow_color")),
                _color_or_none(data.get("arrow_color")),
            )
        if kind == "arrow":
            return Arrow(
                data["id"], tuple(data["start"]), tuple(data["end"]), data["glow"],
                _color_or_none(data.get("color")), _color_or_none(data.get("glow_color")),
            )
        if kind == "step":
            return StepBadge(data["id"], tuple(data["center"]), data["number"], _color_or_none(data.get("color")))
        if kind == "text":
            return TextLabel(
                id=data["id"], pos=tuple(data["pos"]), text=data["text"], size=data["size"],
                color=data["color"], bold=data["bold"], bg=data["bg"], bg_opacity=data["bg_opacity"],
                border=data["border"], border_width=data["border_width"], padding=data["padding"],
                rx=data["rx"], align=TextAlign(data["align"]), outline=data["outline"],
            )
        if kind == "redaction":
            return Redaction(data["id"], Rect(*data["rect"]), data["block"])
        if kind == "magnifier":
            return Magnifier(
                data["id"], Rect(*data["source"]), tuple(data["lens_center"]), data["zoom"],
                LensShape(data["shape"]), data["connector"], _color_or_none(data.get("frame_color")),
                _corner_or_default(data.get("corner")),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise AnnotateError(f"Anotacion invalida en el proyecto ({kind}): {exc}") from exc
    raise AnnotateError(f"Tipo de anotacion desconocido: {kind}")


def _stored_image_path(doc: AnnotationDoc, sidecar: Path) -> str:
    """Nombre de archivo si la captura esta junto al JSON; ruta absoluta si no."""
    if doc.image_path.parent.resolve() == sidecar.parent.resolve():
        return doc.image_path.name
    return str(doc.image_path.resolve())


def save_doc(doc: AnnotationDoc, path: Path | None = None) -> Path:
    """Guarda el proyecto. Sin path usa sidecar_path(doc.image_path)."""
    target = path or sidecar_path(doc.image_path)
    payload = {
        "version": SIDECAR_VERSION,
        "image": _stored_image_path(doc, target),
        "image_size": list(doc.image_size),
        "style_scale": doc.style_scale,
        "padding": doc.padding,
        "palette": palette_to_dict(doc.palette),
        "items": [item_to_dict(i) for i in doc.items],
    }
    try:
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        raise AnnotateError(f"No se pudo guardar el proyecto de anotaciones: {exc}") from exc
    return target


def load_doc(path: Path) -> AnnotationDoc:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotateError(f"No se pudo leer el proyecto {path.name}: {exc}") from exc
    try:
        image_path = Path(data["image"])
        if not image_path.is_absolute():
            image_path = path.parent / image_path
        return AnnotationDoc(
            image_path=image_path,
            image_size=tuple(data["image_size"]),
            items=[item_from_dict(i) for i in data["items"]],
            style_scale=data.get("style_scale"),
            padding=data.get("padding", 0),
            palette=palette_from_dict(data.get("palette")),
        )
    except (KeyError, TypeError) as exc:
        raise AnnotateError(f"Proyecto de anotaciones incompleto ({path.name}): {exc}") from exc
