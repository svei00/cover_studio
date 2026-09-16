import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import AnnotationDoc, TextAlign, TextLabel, text_label_from_preset
from core.annotate.primitives import PRect, PText, label_box, text_label_primitives
from core.annotate.svg import export_png, primitive_to_svg

T = TextLabel("t", (100.0, 100.0), "Hola")


# --- Alerta 2 y Nota 2 -------------------------------------------------------------------------

def test_alerta_2_es_el_rojo_pedido_con_la_forma_de_alerta():
    p = style.TEXT_PRESETS["alerta2"]
    assert (p["bg"], p["border"], p["color"]) == ("#D32F2F", "#8E1B1B", "#FFFFFF")
    assert p["border_width"] == style.TEXT_PRESETS["alerta"]["border_width"] == 3.0   # misma forma que Alerta
    assert p["outline"] is None


def test_nota_2_es_el_amarillo_post_it_pedido_con_la_forma_de_nota():
    p = style.TEXT_PRESETS["nota2"]
    assert (p["bg"], p["border"], p["color"]) == ("#FFF3A3", "#E0C84A", "#333333")
    assert "border_width" not in p and "border_width" not in style.TEXT_PRESETS["nota"]   # el de siempre, como Nota
    assert p["outline"] is None


def test_las_originales_no_se_tocaron():
    assert style.TEXT_PRESETS["alerta"] == {
        "color": style.CREAM, "bg": style.CARD_FILL, "border": style.RED, "border_width": 3.0, "outline": None,
    }
    assert style.TEXT_PRESETS["nota"] == {"color": style.CREAM, "bg": style.CARD_FILL, "border": style.TAN, "outline": None}


def test_los_nuevos_se_crean_como_los_demas():
    a = text_label_from_preset("a", (10.0, 10.0), "Cuidado", "alerta2")
    n = text_label_from_preset("n", (10.0, 10.0), "Recordar", "nota2")
    assert (a.bg, a.border, a.color) == ("#D32F2F", "#8E1B1B", "#FFFFFF")
    assert (n.bg, n.border, n.color) == ("#FFF3A3", "#E0C84A", "#333333")
    base = text_label_from_preset("b", (10.0, 10.0), "x", "alerta")
    # misma forma: todo lo que no es color es igual al de Alerta / Nota
    assert (a.size, a.padding, a.rx, a.border_width, a.bg_opacity, a.bold) == (base.size, base.padding, base.rx, base.border_width, base.bg_opacity, base.bold)
    nota = text_label_from_preset("c", (10.0, 10.0), "x", "nota")
    assert (n.size, n.padding, n.rx, n.border_width, n.bg_opacity) == (nota.size, nota.padding, nota.rx, nota.border_width, nota.bg_opacity)
    assert label_box(a, 1.0) == label_box(replace(base, text=a.text), 1.0)


# --- opacidad en el modelo y el dibujo -----------------------------------------------------------

def test_la_opacidad_por_defecto_es_100_y_no_cambia_el_dibujo():
    assert T.opacity == 1.0 and T.color == "#F1EBDF"
    caja, texto = text_label_primitives(T, 1.0)
    assert (caja.opacity, caja.fill_opacity, texto.opacity) == (1.0, 0.92, 1.0)


def test_la_opacidad_afecta_a_toda_la_etiqueta():
    caja, texto = text_label_primitives(replace(T, opacity=0.5), 1.0)
    assert caja.opacity == 0.5 and caja.fill_opacity == pytest.approx(0.46) and texto.opacity == 0.5   # borde, fondo y letra


def test_svg_de_la_opacidad():
    caja, texto = text_label_primitives(replace(T, opacity=0.5), 1.0)
    assert 'opacity="0.50"' in primitive_to_svg(texto)
    svg_caja = primitive_to_svg(caja)
    assert 'fill-opacity="0.46' in svg_caja and 'stroke-opacity="0.5"' in svg_caja
    # al 100 % el SVG no lleva el atributo (es identico al de siempre)
    assert "opacity" not in primitive_to_svg(text_label_primitives(T, 1.0)[1])
    # y el contorno del texto suelto se atenua junto con la letra (es un solo elemento)
    libre = text_label_from_preset("l", (0.0, 0.0), "x", "libre")
    assert 'opacity="0.30"' in primitive_to_svg(text_label_primitives(replace(libre, opacity=0.3), 1.0)[0])


def test_color_de_la_letra_propio():
    assert text_label_primitives(replace(T, color="#123456"), 1.0)[1].color == "#123456"


# --- archivo --------------------------------------------------------------------------------------

def test_color_y_opacidad_se_guardan_y_se_recuperan():
    t = replace(T, color="#123456", opacity=0.4)
    assert item_from_dict(item_to_dict(t)) == t


def test_una_etiqueta_vieja_sin_opacidad_abre_al_100():
    data = item_to_dict(T)
    del data["opacity"]
    assert item_from_dict(data).opacity == 1.0


@pytest.mark.parametrize("bad", ["x", None, True, -0.1, 1.5, [1]])
def test_una_opacidad_invalida_usa_100(bad):
    data = item_to_dict(T)
    data["opacity"] = bad
    assert item_from_dict(data).opacity == 1.0


def test_un_proyecto_guardado_antes_de_este_cambio_abre_sin_errores(tmp_path):
    """JSON tal como lo escribia la version anterior: etiqueta sin 'opacity' y demas anotaciones sin campos nuevos."""
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "vieja.png")
    viejo = {
        "version": 1, "image": "vieja.png", "image_size": [400, 300], "style_scale": None, "padding": 0,
        "items": [
            {"type": "text", "id": "a1", "pos": [20, 20], "text": "Nota vieja", "size": 28.0, "color": "#F1EBDF",
             "bold": True, "bg": "#1B3350", "bg_opacity": 0.92, "border": "#D4C19C", "border_width": 2.5,
             "padding": 12.0, "rx": 8.0, "align": "left", "outline": None},
            {"type": "marker", "id": "a2", "rect": [100, 100, 80, 40], "arrow": "auto", "glow": True,
             "stroke_color": None, "glow_color": None, "arrow_color": None},
            {"type": "step", "id": "a3", "center": [300, 200], "number": 1, "color": None},
            {"type": "arrow", "id": "a4", "start": [10, 10], "end": [50, 60], "glow": True, "color": None, "glow_color": None},
        ],
    }
    path = tmp_path / "vieja.anotar.json"
    path.write_text(json.dumps(viejo), encoding="utf-8")
    doc = load_doc(path)
    assert [type(i).__name__ for i in doc.items] == ["TextLabel", "Marker", "Step" + "Badge", "Arrow"]
    assert doc.items[0].opacity == 1.0 and doc.items[0].text == "Nota vieja"
    export_png(doc, tmp_path / "salida.png")   # y se exporta igual
    assert Image.open(tmp_path / "salida.png").size == (400, 300)


# --- pixeles: lo que sale en el PNG ---------------------------------------------------------------------

def _blend(fg, bg, a):
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _export(tmp_path, label, name="o.png"):
    Image.new("RGB", (500, 300), (255, 255, 255)).save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", (500, 300), [label], style_scale=1.0)
    export_png(doc, tmp_path / name)
    return Image.open(tmp_path / name).convert("RGB"), label_box(label, 1.0)


def _close(a, b, tol=2):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@pytest.mark.parametrize("preset,bg,border", [("alerta2", "#D32F2F", "#8E1B1B"), ("nota2", "#FFF3A3", "#E0C84A")])
def test_los_estilos_nuevos_se_exportan_con_sus_colores(tmp_path, preset, bg, border):
    label = text_label_from_preset("t", (60.0, 60.0), "Texto de prueba", preset)
    img, box = _export(tmp_path, label)
    y = round(box.y + box.h / 2)
    assert _close(img.getpixel((round(box.x + 4), y)), _blend(_hex(bg), (255, 255, 255), 0.92)), "relleno"
    assert _close(img.getpixel((round(box.x) + 0, y)), _hex(border), 3), "borde"


def test_la_letra_blanca_de_alerta_2_y_la_oscura_de_nota_2(tmp_path):
    for preset, texto in (("alerta2", (255, 255, 255)), ("nota2", (0x33, 0x33, 0x33))):
        label = text_label_from_preset("t", (60.0, 60.0), "WWW iii", preset)
        img, box = _export(tmp_path, label, f"{preset}.png")
        caja = img.crop((round(box.x), round(box.y), round(box.x + box.w), round(box.y + box.h)))
        colores = {c: n for n, c in caja.getcolors(maxcolors=1_000_000)}
        assert colores.get(texto, 0) > 40, preset   # hay letra del color exacto


def test_opacidad_50_aclara_toda_la_etiqueta_en_el_png(tmp_path):
    base = text_label_from_preset("t", (60.0, 60.0), "WWW iii", "nota2")
    pleno, box = _export(tmp_path, base, "pleno.png")
    medio, _ = _export(tmp_path, replace(base, opacity=0.5), "medio.png")
    y = round(box.y + box.h / 2)
    relleno = _blend(_hex("#FFF3A3"), (255, 255, 255), 0.92 * 0.5)
    assert _close(medio.getpixel((round(box.x + 4), y)), relleno)
    # el borde tambien: el trazo (al 50 %) esta sobre el relleno (al 46 %) que cubre la mitad de su ancho
    bajo_el_borde = _blend(_hex("#FFF3A3"), (255, 255, 255), 0.92 * 0.5)
    assert _close(medio.getpixel((round(box.x), y)), _blend(_hex("#E0C84A"), bajo_el_borde, 0.5), 3)
    caja = (round(box.x), round(box.y), round(box.x + box.w), round(box.y + box.h))
    exactos = lambda im: dict((c, n) for n, c in im.crop(caja).getcolors(maxcolors=1_000_000)).get((0x33, 0x33, 0x33), 0)  # noqa: E731
    assert exactos(pleno) > 40 and exactos(medio) == 0                       # la letra tambien se atenua
    oscuro = min(min(c) for _, c in medio.crop(caja).getcolors(maxcolors=1_000_000))
    assert 0x33 + 40 < oscuro                                                  # y su color mas oscuro es el mezclado


def test_opacidad_0_deja_la_etiqueta_invisible(tmp_path):
    label = replace(text_label_from_preset("t", (60.0, 60.0), "Hola", "alerta2"), opacity=0.0)
    img, box = _export(tmp_path, label)
    assert set(c for _, c in img.getcolors(maxcolors=1_000_000)) == {(255, 255, 255)}


def test_el_pintor_de_qt_atenua_igual_que_resvg(qapp):   # dibuja texto: Qt necesita la QApplication (fuentes)
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    label = replace(text_label_from_preset("t", (60.0, 60.0), "Hola", "alerta2"), opacity=0.5)
    img = QImage(500, 300, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    paint_primitives(painter, text_label_primitives(label, 1.0))
    painter.end()
    box = label_box(label, 1.0)
    y = round(box.y + box.h / 2)
    qt = QColor(img.pixel(round(box.x + 4), y))
    esperado = _blend(_hex("#D32F2F"), (255, 255, 255), 0.92 * 0.5)
    assert _close((qt.red(), qt.green(), qt.blue()), esperado)


# --- interfaz -----------------------------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ui.annotate.controller import Tool
from ui.annotate.tab import AnnotateTab


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
    t.doc.items.append(TextLabel("a1", (100.0, 100.0), "Hola mundo"))
    t.controller.select("a1")
    QApplication.processEvents()
    return t


def _item(tab):
    return tab.controller.selected_item()


def _reset_btn(control):
    return control.parentWidget().layout().itemAt(1).widget()


def _choose(tab, key):
    combo = tab.panel._text_preset
    combo.setCurrentIndex(combo.findData(key))
    tab.panel._on_preset_chosen(combo.currentIndex())


def test_el_combo_de_estilo_muestra_alerta_2_y_nota_2_junto_a_los_originales(tab):
    combo = tab.panel._text_preset
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels == ["Elegir preset...", "Nota", "Nota 2", "Exito", "Alerta", "Alerta 2", "Libre (con contorno)"]


def test_elegir_alerta_2_y_nota_2_desde_el_panel(tab):
    _choose(tab, "alerta2")
    assert (_item(tab).bg, _item(tab).border, _item(tab).color, _item(tab).border_width) == ("#D32F2F", "#8E1B1B", "#FFFFFF", 3.0)
    _choose(tab, "nota2")
    assert (_item(tab).bg, _item(tab).border, _item(tab).color) == ("#FFF3A3", "#E0C84A", "#333333")
    tab.controller.undo()   # elegir un estilo es un paso
    assert _item(tab).bg == "#D32F2F"


def test_los_estilos_nuevos_heredan_tamano_alineacion_y_opacidad(tab):
    tab.panel._text_size.setValue(44)
    tab.panel._text_opacity.setValue(50)
    tab.panel._text_align.setCurrentIndex(tab.panel._text_align.findData(TextAlign.CENTER.value))
    for key in ("alerta2", "nota2", "alerta", "nota"):
        _choose(tab, key)
        assert (_item(tab).size, _item(tab).opacity, _item(tab).align) == (44.0, 0.5, TextAlign.CENTER), key


def test_el_selector_de_color_de_la_letra_tiene_el_default_pedido_y_se_restablece(tab):
    p = tab.panel
    assert p._text_color._picker.hex_color().upper() == "#F1EBDF" and not p._text_color._reset.isEnabled()
    p._text_color._on_picked("#123456")
    assert _item(tab).color == "#123456" and p._text_color._reset.isEnabled()
    p._text_color._reset.click()
    assert _item(tab).color == "#F1EBDF"
    p._text_color._on_picked("#654321")
    label = tab.panel._pages.currentWidget().layout().labelForField(p._text_color)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseDClick(label, Qt.LeftButton)       # doble clic en la etiqueta: valor de fabrica
    assert _item(tab).color == "#F1EBDF"


def test_el_control_de_opacidad_va_de_0_a_100_con_default_100(tab):
    p = tab.panel
    assert (p._text_opacity.minimum(), p._text_opacity.maximum(), p._text_opacity.value()) == (0, 100, 100)
    assert not _reset_btn(p._text_opacity).isEnabled()
    p._text_opacity.setValue(50)
    assert _item(tab).opacity == 0.5 and _reset_btn(p._text_opacity).isEnabled()
    _reset_btn(p._text_opacity).click()
    assert _item(tab).opacity == 1.0 and p._text_opacity.value() == 100
    p._text_opacity.setValue(0)
    assert _item(tab).opacity == 0.0


def test_poner_alerta_2_nota_2_y_un_texto_al_50_y_exportar(tab, tmp_path):
    tab.controller.set_style_scale(1.0)
    tab.doc.items.clear()
    tab.doc.items.extend([
        text_label_from_preset("a1", (40.0, 40.0), "Alerta 2", "alerta2"),
        text_label_from_preset("a2", (40.0, 160.0), "Nota 2", "nota2"),
        replace(text_label_from_preset("a3", (40.0, 280.0), "Texto al 50", "nota"), opacity=0.5),
    ])
    tab.controller.changed.emit()
    out = tmp_path / "tres.png"
    assert tab.export_to(out)
    img = Image.open(out).convert("RGB")
    cajas = [label_box(i, 1.0) for i in tab.doc.items]
    assert _close(img.getpixel((round(cajas[0].x + 4), round(cajas[0].y + cajas[0].h / 2))), _blend(_hex("#D32F2F"), (255, 255, 255), 0.92))
    assert _close(img.getpixel((round(cajas[1].x + 4), round(cajas[1].y + cajas[1].h / 2))), _blend(_hex("#FFF3A3"), (255, 255, 255), 0.92))
    assert _close(img.getpixel((round(cajas[2].x + 4), round(cajas[2].y + cajas[2].h / 2))), _blend(_hex(style.CARD_FILL), (255, 255, 255), 0.92 * 0.5))


def test_el_texto_nuevo_sale_con_el_color_y_la_opacidad_de_siempre(tab):
    tab.doc.items.clear()
    tab.tool_buttons[Tool.TEXT].click()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent

    pos = tab.canvas.image_to_view((200.0, 200.0))
    for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(tab.canvas, QMouseEvent(kind, pos, pos, Qt.LeftButton, buttons, Qt.NoModifier))
    nuevo = tab.doc.items[0]
    assert (nuevo.color, nuevo.opacity) == ("#F1EBDF", 1.0)


def test_la_pagina_de_texto_no_se_estira_hasta_llenar_el_panel(tab):
    """Regresion: con el panel en un QScrollArea, la pagina se estiraba a toda la altura y el formulario
    repartia el espacio sobrante entre sus filas (huecos enormes)."""
    QApplication.processEvents()
    pages, viewport = tab.panel._pages, tab.panel._scroll.viewport()
    assert viewport.height() > pages.sizeHint().height() + 100      # sobra espacio en la ventana de prueba...
    assert pages.height() <= pages.sizeHint().height() + 2           # ...y la pagina mide solo lo que necesita
