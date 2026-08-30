"""Controlador de edicion: herramienta activa, seleccion, gestos del mouse y
pila de deshacer/rehacer. La geometria vive en core.annotate.edit; aqui solo se
conecta con Qt.

Patron de los gestos: mientras se arrastra, el documento se modifica en vivo
(sin comandos) y al soltar se empuja UN comando con el estado inicial y final.
Los comandos son idempotentes (aplican un estado, no un delta), asi que
empujarlos sobre un estado ya aplicado no duplica nada."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from core.annotate import edit, lens
from core.annotate.model import (
    Annotation,
    AnnotationDoc,
    Arrow,
    Magnifier,
    Marker,
    Rect,
    Redaction,
    StepBadge,
    text_label_from_preset,
)
from core.annotate.primitives import doc_scale, item_bounds

Point = tuple[float, float]

MIN_RECT = 6.0
MIN_ARROW = 8.0
MIN_LENS_SOURCE = 12.0
PROPERTY_MERGE_ID = 1000
NUDGE_MERGE_ID = 1001
DEFAULT_REDACTION_BLOCK = 12


class Tool(str, Enum):
    SELECT = "select"
    MARKER = "marker"
    ARROW = "arrow"
    STEP = "step"
    TEXT = "text"
    REDACT = "redact"
    LENS = "lens"


_HANDLE_CURSORS = {
    edit.Handle.NW: Qt.SizeFDiagCursor, edit.Handle.SE: Qt.SizeFDiagCursor,
    edit.Handle.NE: Qt.SizeBDiagCursor, edit.Handle.SW: Qt.SizeBDiagCursor,
    edit.Handle.N: Qt.SizeVerCursor, edit.Handle.S: Qt.SizeVerCursor,
    edit.Handle.E: Qt.SizeHorCursor, edit.Handle.W: Qt.SizeHorCursor,
    edit.Handle.START: Qt.CrossCursor, edit.Handle.END: Qt.CrossCursor,
    edit.Handle.LENS: Qt.SizeFDiagCursor,
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
        self, controller: EditController, old: Annotation, new: Annotation, text: str, merge_id: int = -1
    ) -> None:
        super().__init__(text)
        self._controller = controller
        self._old = old
        self._new = new
        self._merge_id = merge_id

    def id(self) -> int:  # noqa: A003 (override de Qt)
        return self._merge_id

    def redo(self) -> None:
        self._controller._set_item(self._new)

    def undo(self) -> None:
        self._controller._set_item(self._old)

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (override de Qt)
        if not isinstance(other, _ReplaceCommand) or other._new.id != self._new.id:
            return False
        self._new = other._new
        return True


class EditController(QObject):
    changed = Signal()
    selectionChanged = Signal()
    toolChanged = Signal(object)
    textEditRequested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.doc: AnnotationDoc | None = None
        self.stack = QUndoStack(self)
        self.tool = Tool.SELECT
        self.selected_id: str | None = None
        self._mode: str | None = None
        self._orig: Annotation | None = None
        self._handle: edit.Handle | None = None
        self._part: str | None = None
        self._grab: Point = (0.0, 0.0)
        self._anchor: Point = (0.0, 0.0)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def set_doc(self, doc: AnnotationDoc | None) -> None:
        self.doc = doc
        self.stack.clear()
        self._mode = None
        self.tool = Tool.SELECT
        self.toolChanged.emit(self.tool)
        self.selected_id = None
        self.selectionChanged.emit()
        self.changed.emit()

    def scale(self) -> float:
        return doc_scale(self.doc) if self.doc else 1.0

    def item_by_id(self, item_id: str | None) -> Annotation | None:
        if self.doc is None or item_id is None:
            return None
        index = edit.find_index(self.doc.items, item_id)
        return None if index is None else self.doc.items[index]

    def selected_item(self) -> Annotation | None:
        return self.item_by_id(self.selected_id)

    def set_tool(self, tool: Tool) -> None:
        if tool is self.tool:
            return
        self.tool = tool
        if tool is not Tool.SELECT:
            self.select(None)
        self.toolChanged.emit(tool)

    def select(self, item_id: str | None) -> None:
        if item_id != self.selected_id:
            self.selected_id = item_id
            self.selectionChanged.emit()

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
        if self.selected_id == item_id:
            self.selected_id = None
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

    # ------------------------------------------------------------------
    # Gestos del mouse (coordenadas en pixeles de imagen)
    # ------------------------------------------------------------------

    def press(self, point: Point, tol: float) -> None:
        if self.doc is None:
            return
        p = edit.clamp_point(point, self.doc.image_size)
        if self.tool is Tool.SELECT:
            self._press_select(p, tol)
        elif self.tool in (Tool.MARKER, Tool.REDACT, Tool.ARROW, Tool.LENS):
            self._begin_create(p)
        elif self.tool is Tool.STEP:
            item = StepBadge(edit.new_id(self.doc.items), p, edit.next_step_number(self.doc.items))
            self._commit_new(item)
        elif self.tool is Tool.TEXT:
            item = text_label_from_preset(edit.new_id(self.doc.items), p, "Texto", "nota")
            self._commit_new(item)
            self.textEditRequested.emit()

    def _press_select(self, p: Point, tol: float) -> None:
        assert self.doc is not None
        selected = self.selected_item()
        if selected is not None:
            handle = edit.hit_handle(selected, p, tol)
            if handle is not None:
                self._mode, self._orig, self._handle = "resize", selected, handle
                return
        hit = edit.hit_test(self.doc.items, p, tol, self.scale())
        self.select(hit)
        if hit is not None:
            self._mode, self._orig, self._grab = "move", self.item_by_id(hit), p
            self._part = edit.hit_lens_part(self._orig, p, tol) if isinstance(self._orig, Magnifier) else None

    def _begin_create(self, p: Point) -> None:
        assert self.doc is not None
        item_id = edit.new_id(self.doc.items)
        if self.tool is Tool.MARKER:
            item: Annotation = Marker(item_id, Rect(p[0], p[1], 0.0, 0.0))
        elif self.tool is Tool.REDACT:
            block = max(6, round(DEFAULT_REDACTION_BLOCK * self.scale()))
            item = Redaction(item_id, Rect(p[0], p[1], 0.0, 0.0), block)
        elif self.tool is Tool.LENS:
            item = Magnifier(item_id, Rect(p[0], p[1], 0.0, 0.0), p)
        else:
            item = Arrow(item_id, p, p)
        self._insert(item)
        self._mode, self._orig, self._anchor = "create", item, p
        self.select(item_id)

    def _commit_new(self, item: Annotation) -> None:
        self.stack.push(_AddCommand(self, item))
        self.select(item.id)
        self.set_tool(Tool.SELECT)

    def move(self, point: Point) -> None:
        if self.doc is None or self._mode is None or self._orig is None:
            return
        p = edit.clamp_point(point, self.doc.image_size)
        if self._mode == "move":
            self._set_item(edit.move_item(self._orig, p[0] - self._grab[0], p[1] - self._grab[1], self._part))
        elif self._mode == "resize" and self._handle is not None:
            self._set_item(edit.resize_item(self._orig, self._handle, p))
        elif self._mode == "create":
            if isinstance(self._orig, Arrow):
                self._set_item(replace(self._orig, end=p))
            elif isinstance(self._orig, Magnifier):
                source = edit.rect_from_points(self._anchor, p)
                self._set_item(replace(self._orig, source=source, lens_center=self._auto_lens_center(self._orig, source)))
            else:
                self._set_item(replace(self._orig, rect=edit.rect_from_points(self._anchor, p)))

    def release(self, point: Point) -> None:
        mode, orig = self._mode, self._orig
        self._mode = None
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
            if self._too_small(current):
                self._remove(orig.id)
            else:
                self.stack.push(_AddCommand(self, current))
                self.set_tool(Tool.SELECT)

    @staticmethod
    def _too_small(item: Annotation) -> bool:
        if isinstance(item, Arrow):
            return abs(item.end[0] - item.start[0]) + abs(item.end[1] - item.start[1]) < MIN_ARROW
        if isinstance(item, Magnifier):
            return item.source.w < MIN_LENS_SOURCE or item.source.h < MIN_LENS_SOURCE
        rect = item.rect  # Marker o Redaction
        return rect.w < MIN_RECT or rect.h < MIN_RECT

    def _auto_lens_center(self, m: Magnifier, source: Rect | None = None) -> Point:
        """Centro automatico del lente de `m` (con su origen, o el dado), esquivando
        las demas anotaciones."""
        assert self.doc is not None
        scale = self.scale()
        obstacles = [b for o in self.doc.items if o.id != m.id and (b := item_bounds(o, scale)) is not None]
        return lens.default_lens_center(source or m.source, m.zoom, m.shape, self.doc.image_size, obstacles)

    def auto_place_selected_lens(self) -> None:
        """Recoloca el lente seleccionado en el lado con mas espacio libre."""
        selected = self.selected_item()
        if isinstance(selected, Magnifier):
            self.edit_selected(lens_center=self._auto_lens_center(selected))

    def cursor_at(self, point: Point, tol: float) -> Qt.CursorShape:
        if self.doc is None:
            return Qt.ArrowCursor
        if self.tool is not Tool.SELECT:
            return Qt.CrossCursor
        selected = self.selected_item()
        if selected is not None:
            handle = edit.hit_handle(selected, point, tol)
            if handle is not None:
                return _HANDLE_CURSORS[handle]
        if edit.hit_test(self.doc.items, point, tol, self.scale()) is not None:
            return Qt.SizeAllCursor
        return Qt.ArrowCursor

    # ------------------------------------------------------------------
    # Acciones sobre la seleccion
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Esc: cancela el gesto en curso; si no hay, vuelve a Seleccionar; si ya
        estaba, deselecciona."""
        if self._mode is not None and self._orig is not None:
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

    def delete_selected(self) -> None:
        selected = self.selected_item()
        if selected is None or self.doc is None:
            return
        index = edit.find_index(self.doc.items, selected.id)
        if index is not None:
            self.stack.push(_RemoveCommand(self, selected, index))

    def nudge(self, dx: float, dy: float) -> None:
        selected = self.selected_item()
        if selected is None:
            return
        moved = edit.move_item(selected, dx, dy)
        if moved != selected:
            self.stack.push(_ReplaceCommand(self, selected, moved, "Mover", NUDGE_MERGE_ID))

    def edit_selected(self, **changes) -> None:
        """Cambia propiedades (campos de la anotacion) de la seleccionada. Los
        cambios seguidos sobre la misma anotacion se fusionan en un solo paso de
        deshacer. Todos los kwargs son campos del dataclass, incluido `text`."""
        selected = self.selected_item()
        if selected is None:
            return
        updated = replace(selected, **changes)
        if isinstance(updated, Magnifier) and ("zoom" in changes or "shape" in changes):
            # un lente mas grande o de otra forma puede quedar encima de su origen o pegado a el
            if lens.is_crowded(updated):
                updated = replace(updated, lens_center=self._auto_lens_center(updated))
        if updated != selected:
            self.stack.push(_ReplaceCommand(self, selected, updated, "Editar", PROPERTY_MERGE_ID))

    def undo(self) -> None:
        self.stack.undo()

    def redo(self) -> None:
        self.stack.redo()
