"""Intensidad y grosor (alcance) del resplandor: una sola fuente de verdad (`style.glow_rings`) para lo que se
dibuja y para las cotas, valores por defecto identicos a los de siempre y proyectos viejos que abren igual."""

from dataclasses import replace

import pytest
from PIL import Image

from core.annotate import style
from core.annotate.bounds import item_box, required_padding
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, Arrow, ArrowSide, Magnifier, Marker, Rect, StepBadge, Stroke
from core.annotate.primitives import (
    PCircle,
    PLine,
    PPolyline,
    PRect,
    PText,
    arrow_primitives,
    item_bounds,
    magnifier_primitives,
    marker_primitives,
    step_primitives,
    stroke_primitives,
)
from core.annotate.svg import export_png

MARCADOR = Marker("m", Rect(100.0, 100.0, 120.0, 60.0), ArrowSide.NONE, glow=True)
FLECHA = Arrow("a", (60.0, 150.0), (340.0, 150.0), glow=True)
PASO = StepBadge("s", (200.0, 150.0), 1, glow=True)
LAPIZ = Stroke("p", ((60.0, 150.0), (340.0, 150.0)), glow=True)
LUPA = Magnifier("l", Rect(40.0, 40.0, 60.0, 40.0), (260.0, 200.0), glow=True, connector_glow=True)


def _opacidades(prims):
    return [p.opacity for p in prims if getattr(p, "opacity", 1.0) < 1.0]


# --- el helper -------------------------------------------------------------------------------------

def test_los_valores_por_defecto_devuelven_los_anillos_de_siempre():
    assert style.glow_rings() == style.GLOW_RINGS
    assert style.glow_rings(1.0, 1.0) == style.GLOW_RINGS


def test_intensidad_multiplica_la_opacidad_y_grosor_el_alcance():
    fuerte = style.glow_rings(2.0, 1.0)
    ancho = style.glow_rings(1.0, 3.0)
    for (off, op), (off2, op2), (off3, op3) in zip(style.GLOW_RINGS, fuerte, ancho):
        assert off2 == off and op2 == pytest.approx(min(1.0, op * 2.0))
        assert off3 == pytest.approx(off * 3.0) and op3 == op


def test_ninguna_opacidad_pasa_de_uno():
    assert max(op for _off, op in style.glow_rings(1000.0, 1.0)) == 1.0


# --- primitivas ------------------------------------------------------------------------------------

def test_sin_ajuste_el_marcador_dibuja_los_anillos_de_siempre():
    prims = marker_primitives(MARCADOR, 1.0, ArrowSide.NONE)
    anillos = [p for p in prims if isinstance(p, PRect)][:len(style.GLOW_RINGS)]
    for (off, op), p in zip(style.GLOW_RINGS, anillos):
        assert p.opacity == op and p.rect == MARCADOR.rect.inflate(off)


@pytest.mark.parametrize("item, hacer", [
    (MARCADOR, lambda i: marker_primitives(i, 1.0, ArrowSide.NONE)),
    (PASO, lambda i: step_primitives(i, 1.0)),
    (LAPIZ, lambda i: stroke_primitives(i, 1.0)),
    (LUPA, lambda i: magnifier_primitives(i, 1.0)),
    (FLECHA, lambda i: arrow_primitives(i, 1.0)),
])
def test_la_intensidad_cambia_la_opacidad_del_halo_y_el_grosor_su_alcance(item, hacer):
    base = hacer(item)
    tenue = hacer(replace(item, glow_strength=0.5))
    ancho = hacer(replace(item, glow_size=2.0))
    assert len(tenue) == len(base) == len(ancho)
    assert sum(_opacidades(tenue)) < sum(_opacidades(base))
    assert sum(_opacidades(ancho)) == pytest.approx(sum(_opacidades(base)))   # el alcance no cambia la opacidad
    def extension(prims):
        return max(
            getattr(p, "width", 0.0) + (p.r if isinstance(p, PCircle) else 0.0)
            + (p.rect.w if isinstance(p, PRect) else 0.0) for p in prims
        )
    assert extension(ancho) > extension(base)


def test_el_conector_de_la_lupa_usa_la_intensidad_y_el_alcance_de_la_lupa():
    def halo(m):
        return [p for p in magnifier_primitives(m, 1.0) if isinstance(p, PLine) and p.stroke == style.GLOW_GOLD]
    base, ancho, tenue = halo(LUPA), halo(replace(LUPA, glow_size=2.0)), halo(replace(LUPA, glow_strength=0.5))
    assert len(base) == len(style.GLOW_RINGS) and max(p.width for p in ancho) > max(p.width for p in base)
    assert sum(p.opacity for p in tenue) < sum(p.opacity for p in base)


def test_la_flecha_suelta_lleva_intensidad_y_alcance_en_su_halo_de_una_capa():
    base = arrow_primitives(FLECHA, 1.0)[0]
    otra = arrow_primitives(replace(FLECHA, glow_strength=2.0, glow_size=2.0), 1.0)[0]
    assert otra.opacity == pytest.approx(base.opacity * 2.0)
    assert otra.width - FLECHA.width == pytest.approx(2 * (base.width - FLECHA.width))


# --- cotas y margen --------------------------------------------------------------------------------

def test_la_caja_del_marcador_crece_con_el_grosor_del_resplandor():
    doc = AnnotationDoc(None, (400, 300), [MARCADOR], style_scale=1.0)
    chico = item_box(doc, replace(MARCADOR, glow_size=0.3), 1.0)
    grande = item_box(doc, replace(MARCADOR, glow_size=3.0), 1.0)
    assert grande.w > item_box(doc, MARCADOR, 1.0).w > chico.w
    assert item_bounds(replace(MARCADOR, glow_size=3.0), 1.0).w > item_bounds(MARCADOR, 1.0).w


def test_el_margen_necesario_crece_con_el_grosor_y_ya_no_hace_falta_con_uno_chico():
    cerca = Marker("m", Rect(10.0, 100.0, 100.0, 60.0), ArrowSide.NONE, glow=True)
    pide = lambda m: required_padding(AnnotationDoc(None, (400, 300), [m], style_scale=1.0))
    assert pide(replace(cerca, glow_size=3.0)) > pide(cerca) > pide(replace(cerca, glow_size=0.3))


# --- exportar --------------------------------------------------------------------------------------

def _export(tmp_path, item, fondo=(255, 255, 255)):
    Image.new("RGB", (400, 300), fondo).save(tmp_path / "f.png")
    doc = AnnotationDoc(tmp_path / "f.png", (400, 300), [item], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def test_un_halo_mas_ancho_llega_mas_lejos_y_uno_mas_fuerte_se_ve_mas(tmp_path):
    base = _export(tmp_path, LAPIZ)
    ancho = _export(tmp_path, replace(LAPIZ, glow_size=3.0))
    fuerte = _export(tmp_path, replace(LAPIZ, glow_strength=2.0))
    lejos = (200, 150 - 28)   # fuera del alcance normal (~20 px), dentro del triple
    assert base.getpixel(lejos) == (255, 255, 255) and ancho.getpixel(lejos) != (255, 255, 255)
    cerca = (200, 150 - 8)
    assert sum(fuerte.getpixel(cerca)) < sum(base.getpixel(cerca)) < 765


def test_el_pintor_de_qt_dibuja_el_halo_ajustado_igual_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    casos = [
        (replace(MARCADOR, glow_strength=1.6, glow_size=2.0), lambda i: marker_primitives(i, 1.0, ArrowSide.NONE), (160, 92)),
        (replace(PASO, glow_strength=0.5, glow_size=2.5), lambda i: [p for p in step_primitives(i, 1.0) if not isinstance(p, PText)], (200, 150 - 30)),   # sin el numero: el texto pide QApplication
        (replace(LAPIZ, glow_strength=1.5, glow_size=2.0), lambda i: stroke_primitives(i, 1.0), (200, 150 - 14)),
        (replace(FLECHA, glow_strength=2.0, glow_size=2.0), lambda i: arrow_primitives(i, 1.0), (200, 150 - 9)),
    ]
    for item, hacer, punto in casos:
        resvg = _export(tmp_path, item).getpixel(punto)
        img = QImage(400, 300, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        paint_primitives(painter, hacer(item))
        painter.end()
        qt = QColor(img.pixel(*punto))
        assert all(abs(a - b) <= 6 for a, b in zip((qt.red(), qt.green(), qt.blue()), resvg)), (type(item).__name__, resvg)


# --- guardar y abrir -------------------------------------------------------------------------------

@pytest.mark.parametrize("item", [MARCADOR, FLECHA, PASO, LAPIZ, LUPA])
def test_intensidad_y_alcance_se_guardan_y_se_recuperan(item):
    ajustado = replace(item, glow_strength=1.5, glow_size=2.5)
    assert item_from_dict(item_to_dict(ajustado)) == ajustado


@pytest.mark.parametrize("item", [MARCADOR, FLECHA, PASO, LAPIZ, LUPA])
def test_un_proyecto_viejo_sin_los_campos_abre_con_los_valores_de_siempre(item):
    viejo = item_to_dict(item)
    viejo.pop("glow_strength"), viejo.pop("glow_size")
    abierto = item_from_dict(viejo)
    assert (abierto.glow_strength, abierto.glow_size) == (1.0, 1.0) and abierto == item


@pytest.mark.parametrize("malo", [None, "mucho", True, -1, 0.0, 99, float("nan")])
def test_un_dato_invalido_de_intensidad_o_alcance_usa_el_de_siempre(malo):
    d = item_to_dict(MARCADOR)
    d["glow_strength"], d["glow_size"] = malo, malo
    abierto = item_from_dict(d)
    assert (abierto.glow_strength, abierto.glow_size) == (1.0, 1.0)


def test_el_ancho_del_anillo_crece_con_el_halo_para_que_no_se_vean_lineas_sueltas():
    assert style.glow_ring_width() == style.GLOW_RING_WIDTH              # por defecto, el de siempre
    assert style.glow_ring_width(0.3) == style.GLOW_RING_WIDTH           # un halo chico no lo adelgaza
    assert style.glow_ring_width(3.0) == pytest.approx(style.GLOW_RING_WIDTH * 3)
    anillos = [p for p in marker_primitives(replace(MARCADOR, glow_size=3.0), 1.0, ArrowSide.NONE) if isinstance(p, PRect)]
    separacion = style.glow_rings(1.0, 3.0)[1][0] - style.glow_rings(1.0, 3.0)[0][0]
    assert anillos[0].width >= separacion                                # cada anillo toca al siguiente
