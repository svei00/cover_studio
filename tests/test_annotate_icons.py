"""Iconos vectoriales (check, cruz, alerta, info, pregunta, estrella, mas, menos): geometria, estilos, colores de fabrica,
dibujo igual en Qt y en resvg, edicion basica y guardado."""

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image

from core.annotate import edit, icons, style
from core.annotate.bounds import item_box, required_padding
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import AnnotationDoc, Icon, IconKind, IconStyle, Rect
from core.annotate.primitives import (
    PCircle,
    PPolygon,
    PPolyline,
    icon_primitives,
    item_bounds,
)
from core.annotate.svg import export_png

KINDS = list(IconKind)
STYLES = list(IconStyle)


def _icon(kind=IconKind.CHECK, st=IconStyle.SEAL, **kw):
    return Icon("i", (200.0, 150.0), kind, st, **kw)


# --- geometria -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_cada_icono_tiene_simbolo_o_es_su_propio_contenedor_y_cabe_en_el_cuadrado_unitario(kind):
    glyph, polygon = icons.glyph(kind), icons.container_polygon(kind)
    assert icons.has_glyph(kind) or polygon is not None
    puntos = [p for stroke in glyph.strokes for p in stroke] + [c for c, _r in glyph.dots] + list(polygon or ())
    assert puntos and all(abs(x) <= 1.0 and abs(y) <= 1.0 for x, y in puntos)   # la caja de seleccion es ese cuadrado


def test_solo_la_alerta_y_la_estrella_tienen_contenedor_propio():
    assert {k for k in KINDS if icons.container_polygon(k) is not None} == {IconKind.WARNING, IconKind.STAR}
    assert len(icons.container_polygon(IconKind.WARNING)) == 3 and len(icons.container_polygon(IconKind.STAR)) == 10
    assert not icons.has_glyph(IconKind.STAR)


def test_el_check_baja_y_sube_y_la_cruz_son_dos_diagonales():
    (a, b, c), = icons.glyph(IconKind.CHECK).strokes
    assert a[0] < b[0] < c[0] and b[1] > a[1] and b[1] > c[1]   # el vertice esta abajo
    assert len(icons.glyph(IconKind.CROSS).strokes) == 2


# --- colores de fabrica ----------------------------------------------------------------------------------

def test_el_check_es_verde_y_la_cruz_roja_por_defecto():
    assert style.ICON_COLORS["check"] == "#21B868" and style.ICON_COLORS["cross"] == "#D32F2F"
    assert set(style.ICON_COLORS) == {k.value for k in IconKind}
    for kind, color in (("check", "#21B868"), ("cross", "#D32F2F")):
        prims = icon_primitives(_icon(IconKind(kind)), 1.0)
        assert any(isinstance(p, PCircle) and p.fill == color for p in prims)


def test_un_color_propio_reemplaza_al_de_fabrica_y_el_simbolo_se_puede_cambiar():
    prims = icon_primitives(_icon(color="#112233", glyph_color="#FFEEDD"), 1.0)
    assert any(isinstance(p, PCircle) and p.fill == "#112233" for p in prims)
    assert any(isinstance(p, PPolyline) and p.stroke == "#FFEEDD" for p in prims)


# --- estilos ---------------------------------------------------------------------------------------------

def test_sello_contorno_y_solo_simbolo_dibujan_distinto():
    sello = icon_primitives(_icon(st=IconStyle.SEAL), 1.0)
    contorno = icon_primitives(_icon(st=IconStyle.OUTLINE), 1.0)
    simbolo = icon_primitives(_icon(st=IconStyle.SYMBOL), 1.0)
    verde = style.ICON_COLORS["check"]
    assert any(isinstance(p, PCircle) and p.fill == verde and not p.stroke for p in sello)            # disco de color
    assert [p for p in sello if isinstance(p, PPolyline)][-1].stroke == style.ICON_LIGHT              # simbolo claro
    assert any(isinstance(p, PCircle) and p.fill == style.ICON_LIGHT and p.stroke == verde for p in contorno)
    assert [p for p in contorno if isinstance(p, PPolyline)][-1].stroke == verde                      # simbolo de color
    assert not any(isinstance(p, PCircle) for p in simbolo)                                           # sin contenedor
    assert [p for p in simbolo if isinstance(p, PPolyline)][-1].stroke == verde


def test_sin_contenedor_el_simbolo_se_agranda():
    caja = lambda prims: max(p.width for p in prims if isinstance(p, PPolyline))
    assert caja(icon_primitives(_icon(st=IconStyle.SYMBOL, ring=False), 1.0)) > caja(icon_primitives(_icon(ring=False), 1.0))


def test_la_estrella_siempre_tiene_contenedor_aunque_se_pida_solo_simbolo():
    for st in STYLES:
        prims = icon_primitives(_icon(IconKind.STAR, st), 1.0)
        assert any(isinstance(p, PPolygon) and len(p.points) == 10 for p in prims)
    assert not any(isinstance(p, PPolyline) for p in icon_primitives(_icon(IconKind.STAR), 1.0))


def test_la_alerta_es_un_triangulo_con_su_signo_de_exclamacion():
    prims = icon_primitives(_icon(IconKind.WARNING), 1.0)
    assert any(isinstance(p, PPolygon) and len(p.points) == 3 and p.fill == style.ICON_COLORS["warning"] for p in prims)
    assert sum(isinstance(p, PCircle) for p in prims) == 1 and sum(isinstance(p, PPolyline) for p in prims) == 1


def test_el_borde_blanco_se_puede_quitar_y_cambia_lo_que_se_dibuja():
    con, sin = icon_primitives(_icon(), 1.0), icon_primitives(_icon(ring=False), 1.0)
    assert len(con) == len(sin) + 1
    anillo = con[0]
    assert isinstance(anillo, PCircle) and anillo.fill == style.ICON_LIGHT and anillo.r > sin[0].r
    for kind in KINDS:   # en todos los estilos y formas el borde aparece (o el halo del simbolo)
        for st in STYLES:
            assert len(icon_primitives(_icon(kind, st), 1.0)) > len(icon_primitives(_icon(kind, st, ring=False), 1.0))


def test_el_tamano_y_la_escala_de_trazo_multiplican_el_radio():
    def radio(prims):
        return max(p.r for p in prims if isinstance(p, PCircle))
    base = radio(icon_primitives(_icon(ring=False), 1.0))
    assert base == pytest.approx(style.ICON_RADIUS)
    assert radio(icon_primitives(_icon(ring=False, size=40.0), 1.0)) == pytest.approx(40.0)
    assert radio(icon_primitives(_icon(ring=False), 2.0)) == pytest.approx(2 * style.ICON_RADIUS)


# --- resplandor ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("st", STYLES)
def test_el_resplandor_agrega_capas_y_ninguna_es_un_disco_opaco(kind, st):
    sin = icon_primitives(_icon(kind, st), 1.0)
    con = icon_primitives(_icon(kind, st, glow=True), 1.0)
    extra = con[:len(con) - len(sin)] if len(con) > len(sin) else []
    assert len(con) > len(sin) and con[-len(sin):] == sin             # lo de siempre queda ENCIMA del halo
    for p in extra:
        assert not (isinstance(p, PCircle) and p.fill) and not (isinstance(p, PPolygon) and p.fill)   # sin relleno opaco
        assert p.opacity < 1.0


def test_la_intensidad_y_el_alcance_del_resplandor_se_aplican_a_los_iconos():
    base = icon_primitives(_icon(glow=True), 1.0)
    tenue = icon_primitives(_icon(glow=True, glow_strength=0.5), 1.0)
    ancho = icon_primitives(_icon(glow=True, glow_size=2.0), 1.0)
    glow = lambda prims: [p for p in prims if isinstance(p, PCircle) and p.stroke == style.GLOW_GOLD]
    assert sum(p.opacity for p in glow(tenue)) < sum(p.opacity for p in glow(base))
    assert max(p.r for p in glow(ancho)) > max(p.r for p in glow(base))


# --- cotas, seleccion y edicion --------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_lo_dibujado_queda_dentro_de_la_caja_del_icono_mas_su_borde(kind):
    i = _icon(kind)
    doc = AnnotationDoc(None, (400, 300), [i], style_scale=1.0)
    box = item_box(doc, i, 1.0)
    r = i.size
    assert box.x >= 200 - r - style.ICON_RING * r * 2 - 1 and box.right <= 200 + r + style.ICON_RING * r * 2 + 1
    assert box.y >= 150 - r - 8 and box.bottom <= 150 + r + 8
    assert item_bounds(i, 1.0) == Rect(180.0, 130.0, 40.0, 40.0)
    assert edit.selection_rect(i, 1.0) == Rect(180.0, 130.0, 40.0, 40.0)


def test_un_icono_pegado_a_la_esquina_pide_margen():
    i = replace(_icon(), center=(10.0, 10.0))
    assert required_padding(AnnotationDoc(None, (400, 300), [i], style_scale=1.0)) >= 10


def test_clic_dentro_o_en_el_borde_selecciona_y_lejos_no():
    i = _icon()
    assert edit.hit_test([i], (200.0, 150.0), 6.0, 1.0) == "i"
    assert edit.hit_test([i], (219.0, 150.0), 6.0, 1.0) == "i"
    assert edit.hit_test([i], (200.0 + 20 + 2, 150.0), 6.0, 1.0) == "i"       # dentro de la tolerancia (la mitad de tol)
    assert edit.hit_test([i], (200.0 + 40, 150.0), 6.0, 1.0) is None
    assert edit.hit_test([i], (200.0, 150.0), 6.0, 2.0) == "i"
    assert edit.hit_test([i], (200.0 + 42, 150.0), 6.0, 2.0) == "i"           # a escala 2 el radio es 40


def test_mover_el_icono_cambia_su_centro_y_conserva_lo_demas():
    i = _icon(IconKind.STAR, IconStyle.OUTLINE, color="#123456", size=30.0, glow=True)
    moved = edit.move_item(i, 12.0, -5.0)
    assert moved.center == (212.0, 145.0) and replace(moved, center=i.center) == i


# --- dibujo igual en Qt y en resvg ----------------------------------------------------------------------

def _export(tmp_path, item, fondo=(255, 255, 255)):
    Image.new("RGB", (400, 300), fondo).save(tmp_path / "f.png")
    doc = AnnotationDoc(tmp_path / "f.png", (400, 300), [item], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def test_el_check_exportado_es_un_disco_verde_con_el_simbolo_blanco_y_borde_blanco(tmp_path):
    img = _export(tmp_path, _icon(size=40.0), fondo=(40, 40, 40))
    verde = tuple(int(style.ICON_COLORS["check"][i:i + 2], 16) for i in (1, 3, 5))
    assert all(abs(a - b) <= 3 for a, b in zip(img.getpixel((200 - 30, 150)), verde))            # el disco, fuera del simbolo
    assert sum(img.getpixel((200 + 41, 150))) > 700                                               # el borde blanco
    assert img.getpixel((200, 150 + 60)) == (40, 40, 40)                                          # fuera no se pinta nada


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("st", STYLES)
def test_el_pintor_de_qt_dibuja_cada_icono_igual_que_resvg(tmp_path, kind, st):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    item = replace(_icon(kind, st, size=40.0), glow=(kind.value in ("check", "warning")))
    resvg = _export(tmp_path, item)
    qimg = QImage(400, 300, QImage.Format_RGB32)
    qimg.fill(QColor(255, 255, 255))
    painter = QPainter(qimg)
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint_primitives(painter, icon_primitives(item, 1.0))
    painter.end()
    diffs = 0
    for dx, dy in ((0, 0), (-30, 0), (30, 0), (0, -30), (0, 30), (-12, 12), (12, -12), (45, 0), (0, 52)):
        q = QColor(qimg.pixel(200 + dx, 150 + dy))
        diffs += sum(abs(a - b) > 14 for a, b in zip((q.red(), q.green(), q.blue()), resvg.getpixel((200 + dx, 150 + dy))))
    assert diffs <= 2, (kind, st, diffs)


# --- guardar y abrir -------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS)
def test_cada_icono_se_guarda_y_se_recupera(kind):
    i = Icon("a1", (10.0, 20.0), kind, IconStyle.OUTLINE, "#112233", "#445566", 31.0, False, True, "#778899", 1.5, 2.5)
    assert item_from_dict(item_to_dict(i)) == i
    assert item_from_dict(item_to_dict(replace(i, color=None, glyph_color=None, glow_color=None))).color is None


def test_un_proyecto_con_iconos_se_guarda_en_disco_y_vuelve_igual(tmp_path):
    Image.new("RGB", (400, 300)).save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", (400, 300), [_icon(k) for k in KINDS])
    doc.items = [replace(it, id=f"i{n}") for n, it in enumerate(doc.items)]
    save_doc(doc)
    assert load_doc(tmp_path / "c.anotar.json").items == doc.items


def test_datos_invalidos_o_faltantes_usan_los_de_fabrica():
    base = item_to_dict(_icon())
    minimo = {k: base[k] for k in ("type", "id", "center")}
    i = item_from_dict(minimo)
    assert (i.kind, i.style, i.color, i.glyph_color, i.size, i.ring, i.glow) == (
        IconKind.CHECK, IconStyle.SEAL, None, None, style.ICON_RADIUS, True, False)
    malo = dict(base, kind="dragon", style=3, color="verde", glyph_color=7, size=-5, ring="si", glow_strength=99, glow_size="x")
    j = item_from_dict(malo)
    assert (j.kind, j.style, j.color, j.glyph_color, j.size) == (IconKind.CHECK, IconStyle.SEAL, None, None, style.ICON_RADIUS)
    assert j.ring is True and (j.glow_strength, j.glow_size) == (1.0, 1.0)
    assert item_from_dict(dict(base, ring=False)).ring is False
