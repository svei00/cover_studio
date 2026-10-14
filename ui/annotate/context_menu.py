"""Menu de clic derecho sobre una anotacion del lienzo (herramienta Seleccionar)."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from core.annotate import overlay as overlay_geometry
from core.annotate.layers import Order
from core.annotate.model import ImageOverlay
from ui.annotate.controller import EditController

ORDER_ACTIONS: tuple[tuple[Order, str], ...] = (
    (Order.FRONT, "Traer al frente"),
    (Order.FORWARD, "Subir un nivel"),
    (Order.BACKWARD, "Bajar un nivel"),
    (Order.BACK, "Enviar atras"),
)


def build_context_menu(controller: EditController, parent: QWidget | None = None) -> QMenu | None:
    """El menu para lo que esta seleccionado (None si no hay nada). Una imagen pegada tiene ademas su sombra y su tamano real;
    el orden y borrar sirven para cualquier anotacion (y para varias a la vez). Cada accion lleva en `data()` su clave para
    las pruebas. Las que no cambiarian nada (traer al frente lo que ya esta arriba) salen deshabilitadas."""
    items = controller.selected_items()
    if not items:
        return None
    menu = QMenu(parent)
    single = items[0] if len(items) == 1 else None
    if isinstance(single, ImageOverlay):
        shadow = menu.addAction("Sombra flotante")
        shadow.setCheckable(True)
        shadow.setChecked(single.shadow)
        shadow.setData("shadow")
        shadow.triggered.connect(lambda on: controller.edit_selected(_merge=False, shadow=bool(on)))
        real = menu.addAction("Tamano real (1:1)")
        real.setData("real_size")
        real.setEnabled(not overlay_geometry.is_real_size(single))
        real.triggered.connect(controller.reset_overlay_size)
        menu.addSeparator()
    for mode, text in ORDER_ACTIONS:
        action: QAction = menu.addAction(text)
        action.setData(mode.value)
        action.setEnabled(controller.can_reorder(mode))
        action.triggered.connect(lambda _checked=False, m=mode: controller.reorder_selected(m))
    menu.addSeparator()
    delete = menu.addAction("Borrar" if len(items) == 1 else f"Borrar ({len(items)})")
    delete.setData("delete")
    delete.triggered.connect(controller.delete_selected)
    return menu
