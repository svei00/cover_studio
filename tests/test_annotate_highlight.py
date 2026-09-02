import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import edit, style
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import AnnotationDoc, Highlight, HighlightMode, Rect
from core.annotate.palette import BRAND_PALETTE, Palette, palette_from_dict, palette_to_dict
from core.annotate.primitives import PRect, build_primitives, highlight_primitives
from core.annotate.svg import build_svg, export_png

HL = Highlight("h", Rect(20, 20, 160, 60))


# --- primitivas -----------------------------------------------------------

def test_el_modo_marcador_multiplica_con_el_color_de_la_paleta():
    (p,) = highlight_primitives(HL, 1.0)
    assert isinstance(p, PRect)
    assert (p.fill, p.fill_opacity, p.blend, p.stroke) == (style.HIGHLIGHT_YELLOW, 1.0, "multiply", None)
    assert p.rx == style.HIGHLIGHT_RADIUS


def test_el_modo_translucido_no_multiplica_y_usa_su_intensidad():
    (p,) = highlight_primitives(replace(HL, mode=HighlightMode.OVERLAY, opacity=0.5), 1.0)
    assert (p.blend, p.fill_opacity) == (None, 0.5)


def test_color_propio_o_de_la_paleta_y_esquinas_con_escala():
    assert highlight_primitives(replace(HL, color="#112233"), 1.0)[0].fill == "#112233"
    assert highlight_primitives(HL, 1.0, Palette(highlight="#445566"))[0].fill == "#445566"
    assert highlight_primitives(replace(HL, radius=5.0), 2.0)[0].rx == 10.0


def test_build_primitives_incluye_el_resaltador_en_su_orden():
    doc = AnnotationDoc(Path("x.png"), (400, 300), [HL])
    assert len(build_primitives(doc)) == 1


def test_la_paleta_del_documento_tiene_el_resaltador():
    assert BRAND_PALETTE.highlight == style.HIGHLIGHT_YELLOW
    assert palette_from_dict(palette_to_dict(Palette(highlight="#AABBCC"))).highlight == "#AABBCC"
    viejo = palette_to_dict(BRAND_PALETTE)
    del viejo["highlight"]
    assert palette_from_dict(viejo).highlight == style.HIGHLIGHT_YELLOW   # un proyecto viejo abre igual


def test_las_muestras_estandar_son_cinco_colores_validos_y_distintos():
    colores = [c for _name, c in style.HIGHLIGHT_SWATCHES]
    assert len(colores) == 5 and len(set(colores)) == 5
    assert all(c.startswith("#") and len(c) == 7 for c in colores)
    assert style.HIGHLIGHT_YELLOW in colores


# --- archivo --------------------------------------------------------------

def test_el_resaltador_se_guarda_y_se_recupera(tmp_path):
    h = Highlight("h", Rect(1, 2, 30, 40), "#AABBCC", HighlightMode.OVERLAY, 0.4, 7.5)
    assert item_from_dict(item_to_dict(h)) == h
    img = tmp_path / "cap.png"
    Image.new("RGB", (100, 100)).save(img)
    sidecar = save_doc(AnnotationDoc(img, (100, 100), [h]))
    assert load_doc(sidecar).items == [h]


@pytest.mark.parametrize("key,bad,field,expected", [
    ("mode", "raro", "mode", HighlightMode.MARKER),
    ("opacity", "x", "opacity", style.HIGHLIGHT_MARKER_OPACITY),
    ("opacity", 0, "opacity", style.HIGHLIGHT_MARKER_OPACITY),
    ("opacity", 5, "opacity", style.HIGHLIGHT_MARKER_OPACITY),
    ("radius", -1, "radius", style.HIGHLIGHT_RADIUS),
    ("radius", True, "radius", style.HIGHLIGHT_RADIUS),
    ("color", "rojo", "color", None),
])
def test_un_dato_invalido_del_resaltador_usa_el_de_fabrica(key, bad, field, expected):
    data = item_to_dict(HL)
    data[key] = bad
    assert getattr(item_from_dict(data), field) == expected


# --- edicion --------------------------------------------------------------

def test_clic_dentro_del_resaltador_lo_selecciona_y_fuera_no():
    assert edit.hit_test([HL], (100, 50), 4, 1.0) == "h"
    assert edit.hit_test([HL], (300, 300), 4, 1.0) is None


def test_asas_mover_y_redimensionar():
    assert len(edit.item_handles(HL)) == 8
    assert edit.move_item(HL, 10, 5).rect == Rect(30, 25, 160, 60)
    assert edit.resize_item(HL, edit.Handle.E, (300, 50)).rect == Rect(20, 20, 280, 60)
    assert edit.selection_rects(HL, 1.0) == [HL.rect]


# --- SVG y pixeles reales -------------------------------------------------

def _capture(path: Path) -> Path:
    """Mitad izquierda blanca, mitad derecha gris oscuro, y una franja negra (el 'texto')."""
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    img.paste((32, 32, 32), (100, 0, 200, 100))
    img.paste((0, 0, 0), (0, 45, 200, 55))
    img.save(path)
    return path


def _export(tmp_path, items) -> Image.Image:
    cap = _capture(tmp_path / "cap.png")
    export_png(AnnotationDoc(cap, (200, 100), items, style_scale=1.0), tmp_path / "out.png")
    return Image.open(tmp_path / "out.png").convert("RGB")


def _close(a, b, tol=3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_el_svg_lleva_la_mezcla_solo_en_modo_marcador(tmp_path):
    cap = _capture(tmp_path / "cap.png")
    marcador = build_svg(AnnotationDoc(cap, (200, 100), [HL]))
    translucido = build_svg(AnnotationDoc(cap, (200, 100), [replace(HL, mode=HighlightMode.OVERLAY, opacity=0.5)]))
    assert "mix-blend-mode:multiply" in marcador and "mix-blend-mode" not in translucido


def test_modo_marcador_sobre_fondo_claro_deja_el_texto_negro(tmp_path):
    out = _export(tmp_path, [Highlight("h", Rect(20, 20, 60, 60))])   # cubre blanco y la franja negra
    assert _close(out.getpixel((50, 30)), (255, 242, 0))   # el amarillo puro sobre blanco
    assert _close(out.getpixel((50, 50)), (0, 0, 0))       # el 'texto' sigue negro


def test_modo_translucido_se_ve_sobre_fondo_oscuro(tmp_path):
    h = Highlight("h", Rect(120, 20, 60, 60), mode=HighlightMode.OVERLAY, opacity=0.5)
    out = _export(tmp_path, [h])
    px = out.getpixel((150, 30))
    assert px[0] > 100 and px[1] > 100   # un amarillo visible, no un casi negro
    marcador = _export(tmp_path, [replace(h, mode=HighlightMode.MARKER, opacity=1.0)]).getpixel((150, 30))
    assert max(marcador) < 40            # el mismo color en modo marcador casi no se ve sobre oscuro


def test_fuera_del_resaltador_la_imagen_no_cambia(tmp_path):
    limpio = _export(tmp_path, [])
    con = _export(tmp_path, [Highlight("h", Rect(20, 20, 60, 60), radius=0.0)])
    assert con.getpixel((5, 5)) == limpio.getpixel((5, 5))
    assert con.getpixel((150, 80)) == limpio.getpixel((150, 80))


def test_el_pintor_de_qt_da_lo_mismo_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    img = QImage(200, 100, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    painter.fillRect(0, 45, 200, 10, QColor(0, 0, 0))
    paint_primitives(painter, highlight_primitives(Highlight("h", Rect(20, 20, 60, 60), radius=0.0), 1.0))
    painter.end()
    blanco, negro = img.pixelColor(50, 30), img.pixelColor(50, 50)
    assert _close((blanco.red(), blanco.green(), blanco.blue()), (255, 242, 0))
    assert _close((negro.red(), negro.green(), negro.blue()), (0, 0, 0))
