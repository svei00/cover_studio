"""Controlador de edicion: herramienta activa, seleccion, gestos del mouse y
pila de deshacer/rehacer. La geometria vive en core.annotate.edit; aqui solo se
conecta con Qt.

Patron de los gestos: mientras se arrastra, el documento se modifica en vivo
(sin comandos) y al soltar se empuja UN comando con el estado inicial y final.
Los comandos son idempotentes (aplican un estado, no un delta), asi que
empujarlos sobre un estado ya aplicado no duplica nada."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from core.annotate import align as aligning
from core.annotate import crop as cropping
from core.annotate import freehand
from core.annotate import edit, lens
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    ArrowSide,
    Highlight,
    HeadStyle,
    Magnifier,
    Marker,
    PenMode,
    Rect,
    Redaction,
    Spotlight,
    StepBadge,
    Icon,
    IconKind,
    IconStyle,
    Stroke,
    text_label_from_preset,
)
from core.annotate.palette import Palette
from core.annotate.primitives import doc_scale, item_bounds, marker_arrow
from core.annotate.style import PEN_MARKER_WIDTH

Point = tuple[float, float]

MIN_RECT = 6.0
MIN_MARQUEE = 4.0   # lado minimo (px de la imagen) para que el rectangulo de seleccion cuente como arrastre
MIN_ARROW = 8.0
MIN_LENS_SOURCE = 12.0
PROPERTY_MERGE_ID = 1000
NUDGE_MERGE_ID = 1001
PADDING_MERGE_ID = 1002
SCALE_MERGE_ID = 1003
DEFAULT_REDACTION_BLOCK = 12


class Tool(str, Enum):
    SELECT = "select"
    MARKER = "marker"
    MARKER_PLAIN = "marker-plain"
    HIGHLIGHT = "highlight"
    ARROW = "arrow"
    LINE = "line"
    PEN = "pen"
    PEN_MARKER = "pen-marker"
    STEP = "step"
    CHECK = "check"   # iconos: el check y la cruz tienen su propio boton; ICON coloca el que se eligio en su menu
    CROSS = "cross"
    ICON = "icon"
    TEXT = "text"
    REDACT = "redact"
    FOCUS = "focus"
    LENS = "lens"
    CROP = "crop"


# Herramientas que se QUEDAN activas tras dibujar (dos recuadros seguidos sin volver a elegirla); se sale con
# Esc o eligiendo otra. El texto no: abre su editor y lo normal es una sola etiqueta.
STICKY_TOOLS = frozenset({
    Tool.MARKER, Tool.MARKER_PLAIN, Tool.HIGHLIGHT, Tool.ARROW, Tool.LINE, Tool.PEN, Tool.PEN_MARKER, Tool.STEP,
    Tool.CHECK, Tool.CROSS, Tool.ICON, Tool.REDACT, Tool.LENS,
})
MAX_LIVE_POINTS = 20000   # puntos del mouse que se guardan mientras se dibuja un trazo (el resto se ignora)

_HANDLE_CURSORS = {
    edit.Handle.NW: Qt.SizeFDiagCursor, edit.Handle.SE: Qt.SizeFDiagCursor,
    edit.Handle.NE: Qt.SizeBDiagCursor, edit.Handle.SW: Qt.SizeBDiagCursor,
    edit.Handle.N: Qt.SizeVerCursor, edit.Handle.S: Qt.SizeVerCursor,
    edit.Handle.E: Qt.SizeHorCursor, edit.Handle.W: Qt.SizeHorCursor,
    edit.Handle.START: Qt.CrossCursor, edit.Handle.END: Qt.CrossCursor,
    edit.Handle.LENS: Qt.SizeFDiagCursor,
    edit.Handle.CONN_START: Qt.CrossCursor, edit.Handle.CONN_END: Qt.CrossCursor,
}


class _AddCommand(QUndoCommand):
    def __init__(self, controller: EditController, item: Annotation) -> None:
        super().__init__("Agregar")
        self._controller = controller
        self._item = item

    def redo(self) -> None:
        self._controller._insert(self._item)

    def undo(self) -> None:
        self._controller._remove(self._item.id)


class _RemoveCommand(QUndoCommand):
    def __init__(self, controller: EditController, item: Annotation, index: int) -> None:
        super().__init__("Borrar")
        self._controller = controller
        self._item = item
        self._index = index

    def redo(self) -> None:
        self._controller._remove(self._item.id)

    def undo(self) -> None:
        self._controller._insert(self._item, self._index)


class _ReplaceCommand(QUndoCommand):
    def __init__(
        self,
        controller: EditController,
        old: Annotation,
        new: Annotation,
        text: str,
        merge_id: int = -1,
        fields: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._old = old
        self._new = new
        self._merge_id = merge_id
        self._fields = fields  # campos editados: solo se fusionan cambios del MISMO campo

    def id(self) -> int:  # noqa: A003 (override de Qt)
        return self._merge_id

    def redo(self) -> None:
        self._controller._set_item(self._new)

    def undo(self) -> None:
        self._controller._set_item(self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (override de Qt)
        if not isinstance(other, _ReplaceCommand) or other._new.id != self._new.id:
            return False
        if other._fields != self._fields:
            return False  # decisiones distintas (forma, luego zoom...) son pasos distintos
        self._new = other._new
        return True


class _MultiReplaceCommand(QUndoCommand):
    """Cambia varias anotaciones a la vez (mover un grupo, alinear, distribuir): UN paso de deshacer. Aplica estados, no
    deltas. Con `merge_id` (las flechas del teclado) los pasos seguidos sobre las mismas anotaciones se fusionan."""

    def __init__(
        self, controller: EditController, olds: list[Annotation], news: list[Annotation], text: str, merge_id: int = -1
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._olds = olds
        self._news = news
        self._merge_id = merge_id

    def id(self) -> int:  # noqa: A003 (override de Qt)
        return self._merge_id

    def redo(self) -> None:
        self._controller._set_items(self._news)

    def undo(self) -> None:
        self._controller._set_items(self._olds)

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (override de Qt)
        if not isinstance(other, _MultiReplaceCommand) or [i.id for i in other._news] != [i.id for i in self._news]:
            return False
        self._news = other._news
        return True


class _DocPropertyCommand(QUndoCommand):
    """Cambia una propiedad del documento (margen, escala de trazo). Los cambios
    seguidos de la misma propiedad se fusionan en un solo paso."""

    def __init__(
        self, controller: EditController, attr: str, old: object, new: object, text: str, merge_id: int
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._attr = attr
        self._old = old
        self._new = new
        self._merge_id = merge_id

    def id(self) -> int:  # noqa: A003 (override de Qt)
        return self._merge_id

    def redo(self) -> None:
        self._controller._set_doc_property(self._attr, self._new)

    def undo(self) -> None:
        self._controller._set_doc_property(self._attr, self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (override de Qt)
        if not isinstance(other, _DocPropertyCommand) or other._attr != self._attr:
            return False
        self._new = other._new
        return True


class EditController(QObject):
    changed = Signal()
    selectionChanged = Signal()
    toolChanged = Signal(object)
    textEditRequested = Signal()
    iconDefaultsChanged = Signal()   # cambio el icono o el estilo con que se colocan los nuevos
    marqueeChanged = Signal()        # el rectangulo de seleccion (arrastrar sobre un hueco) aparecio, cambio o se quito
    cropDraftChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.doc: AnnotationDoc | None = None
        self.stack = QUndoStack(self)
        self.tool = Tool.SELECT
        self._selected: list[str] = []         # ids de lo seleccionado, en orden; el ultimo es el "principal"
        self.marquee: Rect | None = None       # rectangulo de seleccion en curso (solo durante el gesto)
        self._marquee_base: list[str] = []     # lo ya seleccionado cuando el rectangulo SUMA (Ctrl / Shift)
        self._group_orig: dict[str, Annotation] = {}   # estado inicial de cada anotacion al mover un grupo
        self._mode: str | None = None
        self._orig: Annotation | None = None
        self._handle: edit.Handle | None = None
        self._part: str | None = None
        self._grab: Point = (0.0, 0.0)
        self._anchor: Point = (0.0, 0.0)
        self.crop_draft: Rect | None = None   # recorte en curso (solo durante el gesto)
        self.icon_kind = IconKind.WARNING       # el icono que coloca la herramienta Icono (Check y Cruz tienen la suya)
        self.icon_style = IconStyle.SEAL        # el estilo con que se colocan los iconos nuevos (el ultimo que se eligio)
        self._press_arrows: dict[str, tuple[Point, Point]] = {}   # flechas de los marcadores al empezar el gesto
        self._stroke_raw: list[Point] = []   # puntos crudos del mouse del trazo a mano alzada en curso

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def set_doc(self, doc: AnnotationDoc | None) -> None:
        self.doc = doc
        self.stack.clear()
        self._mode = None
        self._set_crop_draft(None)
        self.tool = Tool.SELECT
        self.toolChanged.emit(self.tool)
        self._selected = []
        self._set_marquee(None)
        self.selectionChanged.emit()
        self.changed.emit()

    def scale(self) -> float:
        return doc_scale(self.doc) if self.doc else 1.0

    def marker_arrows(self) -> dict[str, tuple[Point, Point]]:
        """(inicio, punta) de la flecha de cada marcador que la lleva, para seleccionarla."""
        if self.doc is None:
            return {}
        scale = self.scale()
        out: dict[str, tuple[Point, Point]] = {}
        for item in self.doc.items:
            if isinstance(item, Marker) and (arrow := marker_arrow(item, self.doc, scale)) is not None:
                out[item.id] = arrow
        return out

    def item_by_id(self, item_id: str | None) -> Annotation | None:
        if self.doc is None or item_id is None:
            return None
        index = edit.find_index(self.doc.items, item_id)
        return None if index is None else self.doc.items[index]

    @property
    def selected_id(self) -> str | None:
        """La anotacion seleccionada o, si hay varias, la ultima que se sumo."""
        return self._selected[-1] if self._selected else None

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(self._selected)

    def selected_item(self) -> Annotation | None:
        """La anotacion seleccionada, SOLO si hay exactamente una (con varias, editar propiedades no tiene sentido)."""
        return self.item_by_id(self._selected[0]) if len(self._selected) == 1 else None

    def selected_items(self) -> list[Annotation]:
        return [item for i in self._selected if (item := self.item_by_id(i)) is not None]

    def set_icon_defaults(self, kind: IconKind | None = None, style: IconStyle | None = None) -> None:
        """Icono (herramienta Icono) y estilo (todos) con que se colocan los iconos nuevos."""
        if (kind is None or kind is self.icon_kind) and (style is None or style is self.icon_style):
            return
        self.icon_kind = kind or self.icon_kind
        self.icon_style = style or self.icon_style
        self.iconDefaultsChanged.emit()

    def set_tool(self, tool: Tool) -> None:
        if tool is self.tool:
            return
        self.tool = tool
        if self._mode in ("crop_create", "crop_resize"):
            self._mode = None
            self._set_crop_draft(None)
        if tool is not Tool.SELECT:
            self.select(None)
        self.toolChanged.emit(tool)

    def select(self, item_id: str | None) -> None:
        self.select_many([] if item_id is None else [item_id])

    def select_many(self, ids: Sequence[str]) -> None:
        ids = list(dict.fromkeys(ids))   # sin repetidos, en orden
        if ids != self._selected:
            self._selected = ids
            self.selectionChanged.emit()

    def toggle_selected(self, item_id: str) -> None:
        """Ctrl / Shift + clic: suma la anotacion a la seleccion o la quita si ya estaba."""
        if item_id in self._selected:
            self.select_many([i for i in self._selected if i != item_id])
        else:
            self.select_many(self._selected + [item_id])

    def select_all(self) -> None:
        if self.doc is not None:
            self.set_tool(Tool.SELECT)
            self.select_many([item.id for item in self.doc.items])

    def _set_marquee(self, rect: Rect | None) -> None:
        if rect != self.marquee:
            self.marquee = rect
            self.marqueeChanged.emit()

    def items_in_rect(self, rect: Rect) -> list[str]:
        """Ids de las anotaciones que toca el rectangulo (el foco, que abarca toda la captura, solo si lo contiene)."""
        if self.doc is None:
            return []
        scale = self.scale()
        out = []
        for item in self.doc.items:
            boxes = edit.selection_rects(item, scale)
            if isinstance(item, Spotlight):
                hit = all(rect.x <= b.x and rect.y <= b.y and b.right <= rect.right and b.bottom <= rect.bottom for b in boxes)
            else:
                hit = any(rect.intersects(b) for b in boxes)
            if hit:
                out.append(item.id)
        return out

    # ------------------------------------------------------------------
    # Mutaciones internas (sin deshacer; las usan los comandos y los gestos)
    # ------------------------------------------------------------------

    def _insert(self, item: Annotation, index: int | None = None) -> None:
        if self.doc is None or edit.find_index(self.doc.items, item.id) is not None:
            return
        if index is None:
            self.doc.items.append(item)
        else:
            self.doc.items.insert(index, item)
        self.changed.emit()

    def _remove(self, item_id: str) -> None:
        if self.doc is None:
            return
        index = edit.find_index(self.doc.items, item_id)
        if index is None:
            return
        del self.doc.items[index]
        if item_id in self._selected:
            self._selected = [i for i in self._selected if i != item_id]
            self.selectionChanged.emit()
        self.changed.emit()

    def _set_item(self, item: Annotation) -> None:
        if self.doc is None:
            return
        index = edit.find_index(self.doc.items, item.id)
        if index is None:
            return
        self.doc.items[index] = item
        self.changed.emit()

    def _set_items(self, items: Sequence[Annotation]) -> None:
        """Reemplaza varias anotaciones y avisa UNA vez (mover o alinear un grupo no repinta N veces)."""
        if self.doc is None:
            return
        for item in items:
            index = edit.find_index(self.doc.items, item.id)
            if index is not None:
                self.doc.items[index] = item
        self.changed.emit()

    def _set_doc_property(self, attr: str, value: object) -> None:
        if self.doc is None:
            return
        setattr(self.doc, attr, value)
        self.changed.emit()

    def set_padding(self, padding: int) -> None:
        """Margen extra alrededor de la imagen (para que no se recorte el resplandor)."""
        if self.doc is None:
            return
        padding = max(0, int(padding))
        if padding != self.doc.padding:
            self.stack.push(
                _DocPropertyCommand(self, "padding", self.doc.padding, padding, "Margen", PADDING_MERGE_ID)
            )

    def set_palette(self, palette: Palette) -> None:
        """Paleta de colores del documento. Cada cambio es su propio paso de deshacer: los
        colores se eligen en un dialogo modal (una decision, un paso), no se escriben."""
        if self.doc is None or palette == self.doc.palette:
            return
        self.stack.push(_DocPropertyCommand(self, "palette", self.doc.palette, palette, "Colores", -1))

    def _set_crop_draft(self, draft: Rect | None) -> None:
        if draft != self.crop_draft:
            self.crop_draft = draft
            self.cropDraftChanged.emit()

    def crop_rect(self) -> Rect | None:
        """Rectangulo que muestra la herramienta Recortar: el borrador del gesto, el
        recorte vigente o, si no hay, la imagen completa."""
        if self.doc is None:
            return None
        return self.crop_draft or self.doc.crop or cropping.full_rect(self.doc.image_size)

    def set_crop(self, rect: Rect | None) -> None:
        """Aplica un recorte (None lo quita). Cada cambio es su propio paso de deshacer."""
        if self.doc is None:
            return
        new = cropping.normalize_crop(rect, self.doc.image_size)
        if new != self.doc.crop:
            text = "Quitar recorte" if new is None else "Recortar"
            self.stack.push(_DocPropertyCommand(self, "crop", self.doc.crop, new, text, -1))

    def set_style_scale(self, scale: float | None) -> None:
        """Escala de los trazos; None = automatica (segun el ancho de la imagen)."""
        if self.doc is None or scale == self.doc.style_scale:
            return
        self.stack.push(
            _DocPropertyCommand(self, "style_scale", self.doc.style_scale, scale, "Escala", SCALE_MERGE_ID)
        )

    # ------------------------------------------------------------------
    # Gestos del mouse (coordenadas en pixeles de imagen)
    # ------------------------------------------------------------------

    def press(self, point: Point, tol: float, additive: bool = False) -> None:
        """`additive` (Ctrl o Shift) suma o quita de la seleccion en vez de reemplazarla."""
        if self.doc is None:
            return
        p = edit.clamp_point(point, self.doc.image_size)
        if self.tool is Tool.CROP:
            self._press_crop(p, tol)
        elif self.tool is Tool.SELECT:
            self._press_select(p, tol, additive)
        elif self.tool in (
            Tool.MARKER, Tool.MARKER_PLAIN, Tool.HIGHLIGHT, Tool.REDACT, Tool.ARROW, Tool.LINE, Tool.LENS,
            Tool.PEN, Tool.PEN_MARKER, Tool.FOCUS,
        ):
            self._begin_create(p)
        elif self.tool is Tool.STEP:
            item = StepBadge(edit.new_id(self.doc.items), p, edit.next_step_number(self.doc.items))
            self._commit_new(item)
        elif self.tool in (Tool.CHECK, Tool.CROSS, Tool.ICON):
            kind = {Tool.CHECK: IconKind.CHECK, Tool.CROSS: IconKind.CROSS}.get(self.tool, self.icon_kind)
            self._commit_new(Icon(edit.new_id(self.doc.items), p, kind, self.icon_style))
        elif self.tool is Tool.TEXT:
            item = text_label_from_preset(edit.new_id(self.doc.items), p, "Texto", "nota")
            self._commit_new(item)
            self.textEditRequested.emit()

    def _press_crop(self, p: Point, tol: float) -> None:
        assert self.doc is not None
        current = self.crop_rect()
        assert current is not None
        handle = cropping.hit_crop_handle(current, p, tol)
        if handle is not None:
            self._mode, self._handle = "crop_resize", handle
            self._set_crop_draft(current)
        else:
            self._mode, self._anchor = "crop_create", p

    def _press_select(self, p: Point, tol: float, additive: bool = False) -> None:
        assert self.doc is not None
        selected = self.selected_item()
        arrows = self._press_arrows = self.marker_arrows()   # se congelan: durante el gesto no se recalculan
        if selected is not None and not additive:
            handle = edit.hit_handle(selected, p, tol, arrows)
            if handle is not None:
                self._mode, self._orig, self._handle = "resize", selected, handle
                return
        hit = edit.hit_test(self.doc.items, p, tol, self.scale(), arrows)
        if additive and hit is not None:
            self.toggle_selected(hit)   # sumar o quitar: sin arrastre
            return
        if hit is None:   # un hueco: arrastrar dibuja el rectangulo de seleccion; un clic sin arrastrar deselecciona
            self._mode, self._anchor = "marquee", p
            self._marquee_base = list(self._selected) if additive else []
            if not additive:
                self.select(None)
            return
        if hit in self._selected and len(self._selected) > 1:   # arrastrar una de varias seleccionadas las mueve a todas
            self._mode, self._orig, self._grab, self._part = "move_group", None, p, None
            self._group_orig = {item.id: item for item in self.selected_items()}
            return
        self.select(hit)
        if hit is not None:
            self._mode, self._orig, self._grab = "move", self.item_by_id(hit), p
            self._part = None
            if isinstance(self._orig, Magnifier):
                self._part = edit.hit_lens_part(self._orig, p, tol)
            elif isinstance(self._orig, Marker):
                self._part = edit.hit_marker_part(self._orig, p, tol, arrows)

    def _begin_create(self, p: Point) -> None:
        assert self.doc is not None
        item_id = edit.new_id(self.doc.items)
        if self.tool is Tool.MARKER:
            item: Annotation = Marker(item_id, Rect(p[0], p[1], 0.0, 0.0))
        elif self.tool is Tool.MARKER_PLAIN:
            item = Marker(item_id, Rect(p[0], p[1], 0.0, 0.0), arrow=ArrowSide.NONE)
        elif self.tool is Tool.HIGHLIGHT:
            item = Highlight(item_id, Rect(p[0], p[1], 0.0, 0.0))
        elif self.tool is Tool.REDACT:
            block = max(6, round(DEFAULT_REDACTION_BLOCK * self.scale()))
            item = Redaction(item_id, Rect(p[0], p[1], 0.0, 0.0), block)
        elif self.tool is Tool.FOCUS:
            item = Spotlight(item_id, Rect(p[0], p[1], 0.0, 0.0))
        elif self.tool is Tool.LENS:
            item = Magnifier(item_id, Rect(p[0], p[1], 0.0, 0.0), p)
        elif self.tool is Tool.LINE:
            item = Arrow(item_id, p, p, head_end=HeadStyle.NONE)   # una flecha sin puntas
        elif self.tool is Tool.PEN:
            item = Stroke(item_id, (p,))
            self._stroke_raw = [p]
        elif self.tool is Tool.PEN_MARKER:
            item = Stroke(item_id, (p,), mode=PenMode.MARKER, width=PEN_MARKER_WIDTH)
            self._stroke_raw = [p]
        else:
            item = Arrow(item_id, p, p)
        self._insert(item)
        self._mode, self._orig, self._anchor = "create", item, p
        self.select(item_id)

    def _commit_spotlight(self, new: Spotlight) -> None:
        """Solo hay un foco por documento: el nuevo reemplaza al anterior, y todo es UN paso de deshacer."""
        assert self.doc is not None
        previous = [(i, o) for i, o in enumerate(self.doc.items) if isinstance(o, Spotlight) and o.id != new.id]
        if previous:
            self.stack.beginMacro("Agregar foco")
            for index, old in reversed(previous):
                self.stack.push(_RemoveCommand(self, old, index))
            self.stack.push(_AddCommand(self, new))
            self.stack.endMacro()
        else:
            self.stack.push(_AddCommand(self, new))
        self._finish_create()

    def _commit_new(self, item: Annotation) -> None:
        self.stack.push(_AddCommand(self, item))
        self.select(item.id)
        self._finish_create()

    def _finish_create(self) -> None:
        """Tras dibujar: la nueva anotacion queda seleccionada; la herramienta sigue activa si es de las
        que se repiten, y si no vuelve a Seleccionar."""
        if self.tool not in STICKY_TOOLS:
            self.set_tool(Tool.SELECT)

    def move(self, point: Point) -> None:
        if self.doc is None or self._mode is None:
            return
        p = edit.clamp_point(point, self.doc.image_size)
        if self._mode == "crop_create":
            self._set_crop_draft(edit.rect_from_points(self._anchor, p))
            return
        if self._mode == "crop_resize" and self._handle is not None and self.crop_draft is not None:
            self._set_crop_draft(cropping.resize_crop(self.crop_draft, self._handle, p))
            return
        if self._mode == "marquee":
            rect = edit.rect_from_points(self._anchor, p)
            self._set_marquee(rect)
            if rect.w >= MIN_MARQUEE or rect.h >= MIN_MARQUEE:   # un temblor del mouse no cuenta como arrastre
                self.select_many(self._marquee_base + self.items_in_rect(rect))
            return
        if self._mode == "move_group":
            dx, dy = p[0] - self._grab[0], p[1] - self._grab[1]
            self._set_items([edit.move_item(orig, dx, dy) for orig in self._group_orig.values()])
            return
        if self._orig is None:
            return
        if self._mode == "move":
            self._set_item(edit.move_item(
                self._orig, p[0] - self._grab[0], p[1] - self._grab[1], self._part, self._press_arrows))
        elif self._mode == "resize" and self._handle is not None:
            self._set_item(edit.resize_item(self._orig, self._handle, p, arrows=self._press_arrows))
        elif self._mode == "create":
            if isinstance(self._orig, Stroke):
                # a mano alzada: se acumulan los puntos del mouse (con una separacion minima) y se ve en vivo
                if len(self._stroke_raw) < MAX_LIVE_POINTS and freehand.should_add(self._stroke_raw, p):
                    self._stroke_raw.append(p)
                    self._set_item(replace(self._orig, points=tuple(self._stroke_raw)))
            elif isinstance(self._orig, Arrow):
                self._set_item(replace(self._orig, end=p))
            elif isinstance(self._orig, Magnifier):
                source = edit.rect_from_points(self._anchor, p)
                self._set_item(replace(self._orig, source=source, lens_center=self._auto_lens_center(self._orig, source)))
            else:
                self._set_item(replace(self._orig, rect=edit.rect_from_points(self._anchor, p)))

    def release(self, point: Point) -> None:
        mode, orig = self._mode, self._orig
        self._mode = None
        if mode in ("crop_create", "crop_resize"):
            draft, self.crop_draft = self.crop_draft, None
            self.cropDraftChanged.emit()
            # un arrastre minusculo no crea (ni quita) el recorte; las asas ya respetan el minimo
            if draft is not None and draft.w >= cropping.MIN_CROP and draft.h >= cropping.MIN_CROP:
                self.set_crop(draft)
            return
        if mode == "marquee":
            self._set_marquee(None)
            return
        if mode == "move_group":
            olds = list(self._group_orig.values())
            news = [item for o in olds if (item := self.item_by_id(o.id)) is not None]
            self._group_orig = {}
            if len(news) == len(olds) and news != olds:
                self.stack.push(_MultiReplaceCommand(self, olds, news, "Mover"))
            return
        if mode is None or orig is None:
            return
        current = self.item_by_id(orig.id)
        if current is None:
            return
        if mode in ("move", "resize"):
            if current != orig:
                text = "Mover" if mode == "move" else "Redimensionar"
                self.stack.push(_ReplaceCommand(self, orig, current, text))
        elif mode == "create":
            if isinstance(current, Stroke):
                # al soltar: suavizar y simplificar. Se guardan pocos puntos de control, no cada punto del mouse
                current = replace(current, points=freehand.process(self._stroke_raw))
                self._set_item(current)
                self._stroke_raw = []
            if self._too_small(current):
                self._remove(orig.id)
            elif isinstance(current, Spotlight):
                self._commit_spotlight(current)
            else:
                self.stack.push(_AddCommand(self, current))
                self._finish_create()

    @staticmethod
    def _too_small(item: Annotation) -> bool:
        if isinstance(item, Arrow):
            return abs(item.end[0] - item.start[0]) + abs(item.end[1] - item.start[1]) < MIN_ARROW
        if isinstance(item, Magnifier):
            return item.source.w < MIN_LENS_SOURCE or item.source.h < MIN_LENS_SOURCE
        if isinstance(item, Stroke):
            return freehand.path_length(item.points) < freehand.MIN_STROKE_LENGTH   # un clic o un temblor no es un trazo
        rect = item.rect  # Marker, Highlight o Redaction
        return rect.w < MIN_RECT or rect.h < MIN_RECT

    def _auto_lens_center(self, m: Magnifier, source: Rect | None = None) -> Point:
        """Centro automatico del lente de `m` (con su origen, o el dado), esquivando
        las demas anotaciones."""
        assert self.doc is not None
        scale = self.scale()
        obstacles = [b for o in self.doc.items if o.id != m.id and (b := item_bounds(o, scale)) is not None]
        return lens.default_lens_center(
            source or m.source, m.zoom, m.shape, self.doc.image_size, obstacles, region=self.doc.view
        )

    def auto_place_selected_arrow(self) -> None:
        """Devuelve la flecha del marcador seleccionado a la automatica de su lado."""
        selected = self.selected_item()
        if isinstance(selected, Marker) and selected.custom_arrow:
            self.edit_selected(_merge=False, arrow_start=None, arrow_tip=None)

    def auto_place_selected_lens(self) -> None:
        """Recoloca el lente seleccionado en el lado con mas espacio libre."""
        selected = self.selected_item()
        if isinstance(selected, Magnifier):
            self.edit_selected(lens_center=self._auto_lens_center(selected))

    def cursor_at(self, point: Point, tol: float) -> Qt.CursorShape:
        if self.doc is None:
            return Qt.ArrowCursor
        if self.tool is Tool.CROP:
            current = self.crop_rect()
            handle = cropping.hit_crop_handle(current, point, tol) if current is not None else None
            return _HANDLE_CURSORS[handle] if handle is not None else Qt.CrossCursor
        if self.tool is not Tool.SELECT:
            return Qt.CrossCursor
        selected = self.selected_item()
        if selected is not None:
            handle = edit.hit_handle(selected, point, tol, self.marker_arrows())
            if handle is not None:
                return _HANDLE_CURSORS[handle]
        if edit.hit_test(self.doc.items, point, tol, self.scale(), self.marker_arrows()) is not None:
            return Qt.SizeAllCursor
        return Qt.ArrowCursor

    # ------------------------------------------------------------------
    # Acciones sobre la seleccion
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Esc: cancela el gesto en curso; si no hay, vuelve a Seleccionar; si ya
        estaba, deselecciona."""
        if self._mode in ("crop_create", "crop_resize"):
            self._mode = None
            self._set_crop_draft(None)
        elif self._mode == "marquee":
            self._mode = None
            self._set_marquee(None)
        elif self._mode == "move_group":
            self._mode = None
            self._set_items(list(self._group_orig.values()))   # el gesto se cancela: todo vuelve a donde estaba
            self._group_orig = {}
        elif self._mode is not None and self._orig is not None:
            mode, orig = self._mode, self._orig
            self._mode = None
            if mode == "create":
                self._remove(orig.id)
                self.set_tool(Tool.SELECT)
            else:
                self._set_item(orig)
        elif self.tool is not Tool.SELECT:
            self.set_tool(Tool.SELECT)
        else:
            self.select(None)

    def can_align(self) -> bool:
        return len(self._selected) >= 2

    def can_distribute(self) -> bool:
        return len(self._selected) >= aligning.MIN_TO_DISTRIBUTE

    def _apply_deltas(self, items: list[Annotation], deltas: dict[str, aligning.Delta], text: str) -> None:
        """Mueve cada anotacion lo que dice `deltas` en UN paso. De la lupa solo se mueve el LENTE: su origen es la zona
        que se amplia y no debe cambiar de sitio."""
        olds, news = [], []
        for item in items:
            delta = deltas.get(item.id)
            if delta is None:
                continue
            part = "lens" if isinstance(item, Magnifier) else None
            moved = edit.move_item(item, delta[0], delta[1], part)
            if moved != item:
                olds.append(item)
                news.append(moved)
        if news:
            self.stack.push(_MultiReplaceCommand(self, olds, news, text))

    def _selected_boxes(self) -> tuple[list[Annotation], dict[str, Rect]]:
        scale = self.scale()
        items = self.selected_items()
        return items, {item.id: edit.selection_rect(item, scale) for item in items}

    def align_selected(self, mode: aligning.Align) -> None:
        """Alinea las seleccionadas contra la caja que las envuelve a todas (2 o mas)."""
        if not self.can_align():
            return
        items, boxes = self._selected_boxes()
        self._apply_deltas(items, aligning.align_deltas(boxes, mode), "Alinear")

    def distribute_selected(self, axis: aligning.Distribute) -> None:
        """Deja el mismo hueco entre las seleccionadas (3 o mas); las de los extremos no se mueven."""
        if not self.can_distribute():
            return
        items, boxes = self._selected_boxes()
        self._apply_deltas(items, aligning.distribute_deltas(boxes, axis), "Distribuir")

    def delete_selected(self) -> None:
        if self.doc is None:
            return
        found = [(edit.find_index(self.doc.items, item.id), item) for item in self.selected_items()]
        found = sorted(((i, item) for i, item in found if i is not None), key=lambda pair: -pair[0])
        if len(found) == 1:
            self.stack.push(_RemoveCommand(self, found[0][1], found[0][0]))
        elif found:   # de la ultima a la primera: al deshacer cada una vuelve a su lugar
            self.stack.beginMacro("Borrar")
            for index, item in found:
                self.stack.push(_RemoveCommand(self, item, index))
            self.stack.endMacro()

    def nudge(self, dx: float, dy: float) -> None:
        items = self.selected_items()
        if not items:
            return
        moved = [edit.move_item(item, dx, dy) for item in items]
        if moved == items:
            return
        if len(items) == 1:
            self.stack.push(_ReplaceCommand(self, items[0], moved[0], "Mover", NUDGE_MERGE_ID))
        else:
            self.stack.push(_MultiReplaceCommand(self, items, moved, "Mover", NUDGE_MERGE_ID))

    def edit_selected(self, *, _merge: bool = True, **changes) -> None:
        """Cambia propiedades (campos de la anotacion) de la seleccionada. Los
        cambios seguidos sobre la misma anotacion se fusionan en un solo paso de
        deshacer (util al escribir texto); con `_merge=False` cada cambio es su propio
        paso (colores). Los demas kwargs son campos del dataclass, incluido `text`."""
        selected = self.selected_item()
        if selected is None:
            return
        updated = replace(selected, **changes)
        if isinstance(updated, Magnifier) and ("zoom" in changes or "shape" in changes):
            # un lente mas grande o de otra forma puede quedar encima de su origen o pegado a el
            if lens.is_crowded(updated):
                updated = replace(updated, lens_center=self._auto_lens_center(updated))
        if updated != selected:
            merge_id = PROPERTY_MERGE_ID if _merge else -1
            self.stack.push(_ReplaceCommand(self, selected, updated, "Editar", merge_id, frozenset(changes)))

    def undo(self) -> None:
        self.stack.undo()

    def redo(self) -> None:
        self.stack.redo()
