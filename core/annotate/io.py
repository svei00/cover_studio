"""Guardar y cargar el proyecto de anotaciones como JSON junto a la captura
(captura.png -> captura.anotar.json), para poder reabrir y corregir."""

from __future__ import annotations

import json
from pathlib import Path

from core.annotate.crop import normalize_crop
from core.annotate.freehand import MAX_POINTS
from core.annotate.errors import AnnotateError
from core.annotate.palette import is_valid_hex, palette_from_dict, palette_to_dict
from core.annotate.style import (
    DEFAULT_GLOW_SIZE,
    DEFAULT_GLOW_STRENGTH,
    DEFAULT_LENS_CORNER,
    DEFAULT_LENS_FRAME_WIDTH,
    HIGHLIGHT_MARKER_OPACITY,
    HIGHLIGHT_RADIUS,
    MAX_GLOW_SIZE,
    MAX_GLOW_STRENGTH,
    MAX_HIGHLIGHT_RADIUS,
    MAX_LENS_FRAME_WIDTH,
    MAX_LENS_PART_WIDTH,
    MAX_LINE_WIDTH,
    FOCUS_DIM,
    MAX_FOCUS_BLUR,
    MAX_FOCUS_CORNER,
    MAX_FOCUS_DIM,
    MAX_NUMBER_SIZE,
    MAX_PEN_WIDTH,
    MAX_STEP_SIZE,
    MAX_STEP_STROKE,
    MARKER_STROKE,
    MIN_GLOW_SIZE,
    MIN_GLOW_STRENGTH,
    MIN_LENS_FRAME_WIDTH,
    MIN_LENS_PART_WIDTH,
    MIN_LINE_WIDTH,
    MIN_NUMBER_SIZE,
    MIN_PEN_WIDTH,
    MIN_STEP_SIZE,
    MIN_STEP_STROKE,
    PEN_WIDTH,
    STEP_RADIUS,
    STEP_STROKE,
)
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowSide,
    ConnectorRoute,
    Highlight,
    HeadStyle,
    HighlightMode,
    LensShape,
    LineStyle,
    Magnifier,
    Marker,
    PenMode,
    Rect,
    Redaction,
    Spotlight,
    StepBadge,
    StepShape,
    Stroke,
    TextAlign,
    TextLabel,
)

SIDECAR_VERSION = 1


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.stem}.anotar.json")


def _rect_to_list(r: Rect) -> list[float]:
    return [r.x, r.y, r.w, r.h]


def _crop_or_none(value: object, image_size: tuple[int, int]) -> Rect | None:
    """Recorte guardado: una lista [x, y, w, h]; cualquier otra cosa (o un recorte que ya no
    cabe en la imagen) se ignora y se abre la captura completa."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return None
    return normalize_crop(Rect(*(float(v) for v in value)), image_size)


def _point_or_none(value: object) -> tuple[float, float] | None:
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        return float(value[0]), float(value[1])
    return None


def _fraction_or_none(value: object) -> tuple[float, float] | None:
    """Extremo del conector guardado: [u, v] con cada fraccion entre 0 y 1; otra cosa es None (el automatico)."""
    point = _point_or_none(value)
    if point is None or not all(0.0 <= v <= 1.0 for v in point):
        return None
    return point


def _custom_arrow(start: object, tip: object) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Inicio y punta de la flecha movida a mano; si falta o es invalido uno de los dos, la
    flecha vuelve a ser automatica (los dos van juntos)."""
    a, b = _point_or_none(start), _point_or_none(tip)
    return (a, b) if a is not None and b is not None else (None, None)


def _stroke_points(value: object) -> tuple[tuple[float, float], ...]:
    """Puntos de un trazo guardado: una lista de [x, y]. Un trazo sin puntos validos no se puede dibujar: es un
    proyecto danado (TypeError/ValueError lo convierte en AnnotateError)."""
    if not isinstance(value, list) or not value or len(value) > MAX_POINTS:
        raise ValueError("puntos del trazo ausentes o demasiados")
    points = []
    for pair in value:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pair)):
            raise TypeError("punto invalido")
        points.append((float(pair[0]), float(pair[1])))
    return tuple(points)


def _number_or_default(value: object, low: float, high: float, default: float) -> float:
    """Un numero dentro de [low, high]; cualquier otra cosa usa `default`."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
        return float(value)
    return default


def _number_or_none(value: object, low: float, high: float) -> float | None:
    """Un numero dentro de [low, high]; cualquier otra cosa es None (el valor automatico)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
        return float(value)
    return None


def _enum_or_default(enum_type, value: object, default):
    try:
        return enum_type(value)
    except ValueError:
        return default


def _step_shape_or_default(value: object) -> StepShape:
    try:
        return StepShape(value)
    except ValueError:
        return StepShape.CIRCLE


def _highlight_mode_or_default(value: object) -> HighlightMode:
    try:
        return HighlightMode(value)
    except ValueError:
        return HighlightMode.MARKER


def _frame_width_or_default(value: object) -> float:
    """Grosor del marco del lente: un numero dentro de los limites; otra cosa usa el de siempre."""
    if (isinstance(value, (int, float)) and not isinstance(value, bool)
            and MIN_LENS_FRAME_WIDTH <= value <= MAX_LENS_FRAME_WIDTH):
        return float(value)
    return DEFAULT_LENS_FRAME_WIDTH


def _corner_or_default(value: object) -> float:
    """Esquinas del lente: un numero entre 0 y 0.5; cualquier otra cosa usa el valor por defecto."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 0.5:
        return float(value)
    return DEFAULT_LENS_CORNER


def _glow_strength(value: object) -> float:
    return _number_or_default(value, MIN_GLOW_STRENGTH, MAX_GLOW_STRENGTH, DEFAULT_GLOW_STRENGTH)


def _glow_size(value: object) -> float:
    return _number_or_default(value, MIN_GLOW_SIZE, MAX_GLOW_SIZE, DEFAULT_GLOW_SIZE)


def _color_or_none(value: object) -> str | None:
    """Color propio de una anotacion; un dato invalido cuenta como "usa la paleta"."""
    return value if is_valid_hex(value) else None


def item_to_dict(item: Annotation) -> dict:
    if isinstance(item, Marker):
        return {"type": "marker", "id": item.id, "rect": _rect_to_list(item.rect),
                "arrow": item.arrow.value, "glow": item.glow, "stroke_color": item.stroke_color,
                "glow_color": item.glow_color, "arrow_color": item.arrow_color,
                "arrow_start": None if item.arrow_start is None else list(item.arrow_start),
                "arrow_tip": None if item.arrow_tip is None else list(item.arrow_tip),
                "glow_strength": item.glow_strength, "glow_size": item.glow_size}
    if isinstance(item, Arrow):
        return {"type": "arrow", "id": item.id, "start": list(item.start),
                "end": list(item.end), "glow": item.glow, "color": item.color,
                "glow_color": item.glow_color, "head_start": item.head_start.value,
                "head_end": item.head_end.value, "line_style": item.line_style.value,
                "width": item.width, "glow_strength": item.glow_strength, "glow_size": item.glow_size}
    if isinstance(item, StepBadge):
        return {"type": "step", "id": item.id, "center": list(item.center), "number": item.number,
                "color": item.color, "shape": item.shape.value, "fill_color": item.fill_color,
                "number_color": item.number_color, "size": item.size, "number_size": item.number_size,
                "border_width": item.border_width, "glow": item.glow, "glow_color": item.glow_color,
                "glow_strength": item.glow_strength, "glow_size": item.glow_size}
    if isinstance(item, TextLabel):
        return {"type": "text", "id": item.id, "pos": list(item.pos), "text": item.text,
                "size": item.size, "color": item.color, "bold": item.bold, "bg": item.bg,
                "bg_opacity": item.bg_opacity, "border": item.border,
                "border_width": item.border_width, "padding": item.padding, "rx": item.rx,
                "align": item.align.value, "outline": item.outline, "opacity": item.opacity}
    if isinstance(item, Spotlight):
        return {"type": "focus", "id": item.id, "rect": _rect_to_list(item.rect), "dim": item.dim,
                "blur": item.blur, "corner": item.corner}
    if isinstance(item, Redaction):
        return {"type": "redaction", "id": item.id, "rect": _rect_to_list(item.rect), "block": item.block}
    if isinstance(item, Magnifier):
        return {"type": "magnifier", "id": item.id, "source": _rect_to_list(item.source),
                "lens_center": list(item.lens_center), "zoom": item.zoom,
                "shape": item.shape.value, "connector": item.connector, "frame_color": item.frame_color,
                "corner": item.corner, "frame_width": item.frame_width, "glow": item.glow,
                "glow_color": item.glow_color, "frame_style": item.frame_style.value,
                "source_color": item.source_color, "source_width": item.source_width,
                "source_style": item.source_style.value, "connector_color": item.connector_color,
                "connector_width": item.connector_width, "connector_style": item.connector_style.value,
                "connector_glow": item.connector_glow, "glow_strength": item.glow_strength,
                "glow_size": item.glow_size,
                "connector_start": None if item.connector_start is None else list(item.connector_start),
                "connector_end": None if item.connector_end is None else list(item.connector_end),
                "connector_route": item.connector_route.value}
    if isinstance(item, Stroke):
        return {"type": "stroke", "id": item.id, "points": [[x, y] for x, y in item.points], "color": item.color,
                "mode": item.mode.value, "width": item.width, "opacity": item.opacity, "glow": item.glow,
                "glow_color": item.glow_color, "glow_strength": item.glow_strength, "glow_size": item.glow_size}
    if isinstance(item, Highlight):
        return {"type": "highlight", "id": item.id, "rect": _rect_to_list(item.rect), "color": item.color,
                "mode": item.mode.value, "opacity": item.opacity, "radius": item.radius}
    raise AnnotateError(f"Anotacion desconocida: {type(item).__name__}")


def item_from_dict(data: dict) -> Annotation:
    kind = data.get("type")
    try:
        if kind == "marker":
            return Marker(
                data["id"], Rect(*data["rect"]), ArrowSide(data["arrow"]), data["glow"],
                _color_or_none(data.get("stroke_color")), _color_or_none(data.get("glow_color")),
                _color_or_none(data.get("arrow_color")),
                *_custom_arrow(data.get("arrow_start"), data.get("arrow_tip")),
                _glow_strength(data.get("glow_strength")), _glow_size(data.get("glow_size")),
            )
        if kind == "arrow":
            return Arrow(
                data["id"], tuple(data["start"]), tuple(data["end"]), data["glow"],
                _color_or_none(data.get("color")), _color_or_none(data.get("glow_color")),
                _enum_or_default(HeadStyle, data.get("head_start"), HeadStyle.NONE),
                _enum_or_default(HeadStyle, data.get("head_end"), HeadStyle.ARROW),
                _enum_or_default(LineStyle, data.get("line_style"), LineStyle.SOLID),
                _number_or_default(data.get("width"), MIN_LINE_WIDTH, MAX_LINE_WIDTH, MARKER_STROKE),
                _glow_strength(data.get("glow_strength")), _glow_size(data.get("glow_size")),
            )
        if kind == "step":
            return StepBadge(
                data["id"], tuple(data["center"]), data["number"], _color_or_none(data.get("color")),
                _step_shape_or_default(data.get("shape")), _color_or_none(data.get("fill_color")),
                _color_or_none(data.get("number_color")),
                _number_or_default(data.get("size"), MIN_STEP_SIZE, MAX_STEP_SIZE, STEP_RADIUS),
                _number_or_none(data.get("number_size"), MIN_NUMBER_SIZE, MAX_NUMBER_SIZE),
                _number_or_default(data.get("border_width"), MIN_STEP_STROKE, MAX_STEP_STROKE, STEP_STROKE),
                data.get("glow") is True, _color_or_none(data.get("glow_color")),
                _glow_strength(data.get("glow_strength")), _glow_size(data.get("glow_size")),
            )
        if kind == "text":
            return TextLabel(
                id=data["id"], pos=tuple(data["pos"]), text=data["text"], size=data["size"],
                color=data["color"], bold=data["bold"], bg=data["bg"], bg_opacity=data["bg_opacity"],
                border=data["border"], border_width=data["border_width"], padding=data["padding"],
                rx=data["rx"], align=TextAlign(data["align"]), outline=data["outline"],
                opacity=_number_or_default(data.get("opacity"), 0.0, 1.0, 1.0),
            )
        if kind == "focus":
            return Spotlight(
                data["id"], Rect(*data["rect"]),
                _number_or_default(data.get("dim"), 0.0, MAX_FOCUS_DIM, FOCUS_DIM),
                _number_or_default(data.get("blur"), 0.0, MAX_FOCUS_BLUR, 0.0),
                _number_or_default(data.get("corner"), 0.0, MAX_FOCUS_CORNER, 0.0),
            )
        if kind == "redaction":
            return Redaction(data["id"], Rect(*data["rect"]), data["block"])
        if kind == "magnifier":
            return Magnifier(
                data["id"], Rect(*data["source"]), tuple(data["lens_center"]), data["zoom"],
                LensShape(data["shape"]), data["connector"], _color_or_none(data.get("frame_color")),
                _corner_or_default(data.get("corner")),
                _frame_width_or_default(data.get("frame_width")),
                data.get("glow") is True, _color_or_none(data.get("glow_color")),
                _enum_or_default(LineStyle, data.get("frame_style"), LineStyle.SOLID),
                _color_or_none(data.get("source_color")),
                _number_or_none(data.get("source_width"), MIN_LENS_PART_WIDTH, MAX_LENS_PART_WIDTH),
                _enum_or_default(LineStyle, data.get("source_style"), LineStyle.DASHED),
                _color_or_none(data.get("connector_color")),
                _number_or_none(data.get("connector_width"), MIN_LENS_PART_WIDTH, MAX_LENS_PART_WIDTH),
                _enum_or_default(LineStyle, data.get("connector_style"), LineStyle.SOLID),
                data.get("connector_glow") is True,
                _glow_strength(data.get("glow_strength")), _glow_size(data.get("glow_size")),
                _fraction_or_none(data.get("connector_start")), _fraction_or_none(data.get("connector_end")),
                _enum_or_default(ConnectorRoute, data.get("connector_route"), ConnectorRoute.STRAIGHT),
            )
        if kind == "stroke":
            return Stroke(
                data["id"], _stroke_points(data["points"]), _color_or_none(data.get("color")),
                _enum_or_default(PenMode, data.get("mode"), PenMode.PEN),
                _number_or_default(data.get("width"), MIN_PEN_WIDTH, MAX_PEN_WIDTH, PEN_WIDTH),
                _number_or_default(data.get("opacity"), 0.0, 1.0, 1.0),
                data.get("glow") is True, _color_or_none(data.get("glow_color")),
                _glow_strength(data.get("glow_strength")), _glow_size(data.get("glow_size")),
            )
        if kind == "highlight":
            return Highlight(
                data["id"], Rect(*data["rect"]), _color_or_none(data.get("color")),
                _highlight_mode_or_default(data.get("mode")),
                _number_or_default(data.get("opacity"), 0.05, 1.0, HIGHLIGHT_MARKER_OPACITY),
                _number_or_default(data.get("radius"), 0.0, MAX_HIGHLIGHT_RADIUS, HIGHLIGHT_RADIUS),
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
        "crop": None if doc.crop is None else _rect_to_list(doc.crop),
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
        image_size = tuple(data["image_size"])
        return AnnotationDoc(
            image_path=image_path,
            image_size=image_size,
            items=[item_from_dict(i) for i in data["items"]],
            style_scale=data.get("style_scale"),
            padding=data.get("padding", 0),
            palette=palette_from_dict(data.get("palette")),
            crop=_crop_or_none(data.get("crop"), image_size),
        )
    except (KeyError, TypeError) as exc:
        raise AnnotateError(f"Proyecto de anotaciones incompleto ({path.name}): {exc}") from exc
