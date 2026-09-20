import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.annotate import edit, style
from core.annotate.errors import AnnotateError
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Magnifier, Marker, Rect, Redaction, Spotlight
from core.annotate.raster import active_spotlight, apply_redactions, apply_spotlight
from core.annotate.svg import render_bytes
from ui.annotate.controller import STICKY_TOOLS, Tool
from ui.annotate.panel import _PAGE_FOCUS
from ui.annotate.tab import AnnotateTab


def _checker(size=(400, 300)):
    """Imagen con detalle de alta frecuencia (para que el desenfoque se note)."""
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    for x in range(0, size[0], 2):
        for y in range(0, size[1], 2):
            if (x // 2 + y // 2) % 2 == 0:
                img.putpixel((x, y), (0, 0, 0, 255))
                img.putpixel((x + 1, y), (0, 0, 0, 255))
    return img


# --- bitmap -------------------------------------------------------------------


def test_sin_foco_devuelve_la_misma_imagen():
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    assert apply_spotlight(img, []) is img
    assert apply_spotlight(img, [Spotlight("f", Rect(10, 10, 20, 20), dim=0.0, blur=0.0)]) is img


def test_oscurecer_deja_la_zona_y_oscurece_el_resto():
    img = Image.new("RGBA", (100, 100), (200, 200, 200, 255))
    out = apply_spotlight(img, [Spotlight("f", Rect(20, 20, 40, 40), dim=0.5)])
    assert out.getpixel((30, 30)) == (200, 200, 200, 255)           # dentro: intacto
    assert out.getpixel((60, 60)) == (100, 100, 100, 255)           # (60,60) ya es borde: fuera
    assert out.getpixel((5, 5)) == (100, 100, 100, 255)             # fuera: 50 % de negro
    assert out.getpixel((59, 59)) == (200, 200, 200, 255)           # ultimo pixel de la zona


def test_desenfocar_suaviza_fuera_y_no_toca_dentro():
    img = _checker()
    out = apply_spotlight(img, [Spotlight("f", Rect(100, 100, 100, 100), dim=0.0, blur=6.0)])
    assert out.crop((120, 120, 180, 180)).tobytes() == img.crop((120, 120, 180, 180)).tobytes()
    lo, hi = out.crop((250, 150, 290, 190)).convert("L").getextrema()
    assert hi - lo < 40                                               # el tablero se volvio gris casi uniforme
    lo, hi = img.crop((250, 150, 290, 190)).convert("L").getextrema()
    assert hi - lo == 255


def test_oscurecer_y_desenfocar_se_combinan():
    img = _checker()
    out = apply_spotlight(img, [Spotlight("f", Rect(100, 100, 100, 100), dim=0.5, blur=6.0)])
    px = out.getpixel((300, 200))
    assert max(px[:3]) < 160                                           # oscurecido (gris medio * 0.5 aprox.)


def test_las_esquinas_redondeadas_dejan_oscura_la_esquina_de_la_zona():
    img = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    square = apply_spotlight(img, [Spotlight("f", Rect(50, 50, 100, 100), dim=0.8)])
    rounded = apply_spotlight(img, [Spotlight("f", Rect(50, 50, 100, 100), dim=0.8, corner=30)])
    assert square.getpixel((52, 52))[0] == 255
    assert rounded.getpixel((52, 52))[0] < 100                         # la esquina se redondeo: ahora es fondo
    assert rounded.getpixel((100, 100)) == (255, 255, 255, 255)        # el centro sigue nitido


def test_si_hay_varios_focos_cuenta_el_ultimo():
    img = Image.new("RGBA", (100, 100), (200, 200, 200, 255))
    a, b = Spotlight("a", Rect(0, 0, 30, 30), dim=0.5), Spotlight("b", Rect(60, 60, 30, 30), dim=0.5)
    assert active_spotlight([a, b]) is b
    out = apply_spotlight(img, [a, b])
    assert out.getpixel((10, 10)) == (100, 100, 100, 255)             # fuera del ultimo: oscuro
    assert out.getpixel((70, 70)) == (200, 200, 200, 255)


def test_zona_fuera_de_la_imagen_oscurece_todo():
    img = Image.new("RGBA", (50, 50), (200, 200, 200, 255))
    out = apply_spotlight(img, [Spotlight("f", Rect(500, 500, 10, 10), dim=0.5)])
    assert out.getpixel((25, 25)) == (100, 100, 100, 255)


def test_el_pixelado_sigue_pixelado_bajo_el_foco():
    img = _checker()
    redactions = [Redaction("r", Rect(20, 20, 60, 60), 20)]
    spot = [Spotlight("f", Rect(0, 0, 200, 200), dim=0.5)]
    pixelated = apply_redactions(img, redactions)
    out = apply_spotlight(pixelated, redactions + spot)
    assert out.crop((20, 20, 80, 80)).tobytes() == pixelated.crop((20, 20, 80, 80)).tobytes()   # zona dentro: tal cual


# --- exportar: lupas claras, anotaciones por encima --------------------------------


def _doc(tmp_path, items):
    path = tmp_path / "cap.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(path)
    return AnnotationDoc(image_path=path, image_size=(400, 300), items=items)


def _png(doc):
    return Image.open(io.BytesIO(render_bytes(doc))).convert("RGB")


def test_exportar_oscurece_el_fondo_y_respeta_la_zona(tmp_path):
    doc = _doc(tmp_path, [Spotlight("f", Rect(100, 100, 100, 100), dim=0.6)])
    img = _png(doc)
    assert img.getpixel((150, 150)) == (255, 255, 255)
    assert img.getpixel((10, 10))[0] < 120


def test_la_lupa_no_sale_oscurecida_por_el_foco(tmp_path):
    lens = Magnifier("a2", Rect(300, 200, 30, 30), (330.0, 90.0), 2.0)
    doc = _doc(tmp_path, [Spotlight("f", Rect(10, 10, 60, 60), dim=0.8), lens])
    img = _png(doc)
    assert img.getpixel((330, 90)) == (255, 255, 255)                  # dentro del lente: claro
    assert img.getpixel((330, 200))[0] < 80                            # el mismo fondo, fuera de la lupa: oscuro


def test_las_anotaciones_van_por_encima_del_foco(tmp_path):
    marker = Marker("m", Rect(300, 200, 60, 40))
    spot = Spotlight("f", Rect(10, 10, 60, 60), dim=0.8)
    with_spot = _png(_doc(tmp_path, [spot, marker]))
    without = _png(_doc(tmp_path, [marker]))
    # el trazo del marcador (opaco) se ve igual con y sin foco: el foco queda por debajo
    assert with_spot.getpixel((300, 220)) == without.getpixel((300, 220)) != (255, 255, 255)
    # y el fondo de al lado si cambia
    assert with_spot.getpixel((200, 150)) != without.getpixel((200, 150))


# --- proyecto -----------------------------------------------------------------------


def test_el_foco_se_guarda_y_se_recupera():
    s = Spotlight("a7", Rect(10, 20, 30, 40), dim=0.7, blur=12.0, corner=9.0)
    data = item_to_dict(s)
    assert data["type"] == "focus"
    assert item_from_dict(data) == s


def test_proyecto_antiguo_o_con_valores_malos_cae_a_los_de_fabrica():
    s = item_from_dict({"type": "focus", "id": "a1", "rect": [1, 2, 3, 4]})
    assert (s.dim, s.blur, s.corner) == (style.FOCUS_DIM, 0.0, 0.0)
    bad = item_from_dict({"type": "focus", "id": "a1", "rect": [1, 2, 3, 4], "dim": "x", "blur": 9999, "corner": None})
    assert bad.dim == style.FOCUS_DIM and bad.blur == 0.0 and bad.corner == 0.0


def test_foco_sin_zona_es_un_proyecto_danado():
    with pytest.raises(AnnotateError):
        item_from_dict({"type": "focus", "id": "a"})


# --- seleccion y edicion --------------------------------------------------------------


def test_solo_el_borde_del_foco_responde_al_clic():
    s = Spotlight("f", Rect(100, 100, 200, 150))
    assert edit.hit_item(s, (100, 200), 6, 1.0)           # borde
    assert not edit.hit_item(s, (200, 175), 6, 1.0)       # interior
    assert not edit.hit_item(s, (20, 20), 6, 1.0)         # fondo


def test_clic_en_el_interior_selecciona_lo_que_hay_debajo_y_si_no_hay_nada_el_foco():
    s = Spotlight("f", Rect(100, 100, 200, 150))
    m = Marker("m", Rect(150, 140, 60, 40))
    assert edit.hit_test([s, m], (150, 160), 6, 1.0) == "m"
    assert edit.hit_test([s], (200, 175), 6, 1.0) == "f"
    assert edit.hit_test([s], (20, 20), 6, 1.0) is None


def test_mover_y_redimensionar_el_foco():
    s = Spotlight("f", Rect(100, 100, 200, 150), dim=0.7, blur=5.0)
    moved = edit.move_item(s, 10, -5)
    assert moved.rect == Rect(110, 95, 200, 150) and moved.dim == 0.7 and moved.blur == 5.0
    assert set(edit.item_handles(s)) == set(edit.rect_handles(s.rect))
    resized = edit.resize_item(s, edit.Handle.SE, (400, 300))
    assert resized.rect == Rect(100, 100, 300, 200)


# --- controlador ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (800, 500), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    t.load_capture(tmp_path / "cap.png")
    QApplication.processEvents()
    return t


def _mouse(canvas, kind, image_pt, buttons=Qt.LeftButton, button=Qt.LeftButton):
    pos = canvas.image_to_view(image_pt)
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier))


def drag(canvas, a, b):
    _mouse(canvas, QEvent.MouseButtonPress, a)
    _mouse(canvas, QEvent.MouseMove, b, buttons=Qt.LeftButton, button=Qt.NoButton)
    _mouse(canvas, QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)


def _spots(tab):
    return [i for i in tab.doc.items if isinstance(i, Spotlight)]


def test_el_foco_no_es_de_las_herramientas_que_se_repiten():
    assert Tool.FOCUS not in STICKY_TOOLS


def test_dibujar_el_foco_lo_crea_y_vuelve_a_seleccionar(tab):
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (100, 100), (400, 300))
    (s,) = _spots(tab)
    assert (s.dim, s.blur) == (style.FOCUS_DIM, 0.0)
    assert tab.controller.tool is Tool.SELECT and tab.controller.selected_id == s.id
    assert tab.controller.stack.count() == 1


def test_el_foco_nuevo_reemplaza_al_anterior_en_un_solo_paso(tab):
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (100, 100), (300, 250))
    (first,) = _spots(tab)
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (400, 300), (700, 450))
    (second,) = _spots(tab)
    assert second.id != first.id and abs(second.rect.x - 400) < 1e-6
    tab.controller.undo()
    assert _spots(tab) == [first]                       # un solo deshacer devuelve el anterior
    tab.controller.redo()
    assert _spots(tab) == [second]


def test_un_arrastre_minusculo_no_reemplaza_el_foco_existente(tab):
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (100, 100), (300, 250))
    (first,) = _spots(tab)
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (500, 300), (501, 301))
    assert _spots(tab) == [first]


# --- panel y vista previa ---------------------------------------------------------------


def test_el_panel_edita_oscurecer_desenfocar_y_esquinas(tab):
    tab.tool_buttons[Tool.FOCUS].click()
    drag(tab.canvas, (100, 100), (400, 300))
    p = tab.panel
    assert p._pages.currentIndex() == _PAGE_FOCUS
    assert p._focus_dim.value() == round(style.FOCUS_DIM * 100)
    p._focus_dim.setValue(80)
    p._focus_blur.setValue(10.0)
    p._focus_corner.setValue(25.0)
    QApplication.processEvents()
    (s,) = _spots(tab)
    assert (s.dim, s.blur, s.corner) == (0.8, 10.0, 25.0)


def test_la_vista_previa_aplica_el_foco_y_la_lupa_no_se_oscurece(tab):
    tab.doc.items.append(Spotlight("f", Rect(100, 100, 200, 150), dim=0.8))
    tab.doc.items.append(Magnifier("l", Rect(500, 300, 40, 40), (600.0, 80.0), 2.0))
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert tab._base_qimage.pixelColor(150, 150).red() == 255           # zona
    assert tab._base_qimage.pixelColor(700, 450).red() < 80             # fondo oscuro
    lens_img = tab._lens_images()["l"]
    assert lens_img.pixelColor(10, 10).red() == 255                     # la lupa se recorta sin foco


def test_quitar_el_foco_restaura_la_vista_previa(tab):
    tab.doc.items.append(Spotlight("f", Rect(100, 100, 200, 150), dim=0.8))
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert tab._base_qimage.pixelColor(700, 450).red() < 80
    tab.doc.items.clear()
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert tab._base_qimage.pixelColor(700, 450).red() == 255


def test_cambiar_un_pixelado_con_foco_activo_rehace_la_imagen_con_foco(tab):
    tab.doc.items.append(Spotlight("f", Rect(100, 100, 200, 150), dim=0.8))
    tab.controller.changed.emit()
    QApplication.processEvents()
    tab.doc.items.append(Redaction("r", Rect(600, 400, 50, 50), 10))
    tab.controller.changed.emit()
    QApplication.processEvents()
    assert tab._base_qimage.pixelColor(700, 450).red() < 80             # sigue con foco tras el pixelado
