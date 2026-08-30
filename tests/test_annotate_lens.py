import math

import pytest

from core.annotate.lens import (
    connector_segments,
    contains_in_lens,
    crop_box,
    default_lens_center,
    effective_source,
    is_crowded as lens_is_crowded,
    lens_corner_radius,
    lens_rect,
    lens_size,
    near_source_border,
)
from core.annotate.model import LensShape, Magnifier, Rect

SRC = Rect(100, 100, 60, 40)


def circle(**kw):
    return Magnifier("l", kw.pop("source", SRC), kw.pop("center", (400.0, 300.0)), kw.pop("zoom", 2.0),
                     LensShape.CIRCLE, kw.pop("connector", True))


def rounded(**kw):
    return Magnifier("l", kw.pop("source", SRC), kw.pop("center", (400.0, 300.0)), kw.pop("zoom", 2.0),
                     LensShape.ROUNDED, kw.pop("connector", True))


def test_origen_circular_es_el_cuadrado_centrado_de_lado_max():
    src = effective_source(circle())
    assert src.w == src.h == 60 and src.center == SRC.center


def test_origen_rectangular_es_el_original():
    assert effective_source(rounded()) == SRC


def test_el_lente_mide_origen_por_zoom_y_esta_centrado():
    assert lens_size(circle(zoom=3.0)) == (180.0, 180.0)
    r = lens_rect(rounded(zoom=2.5, center=(500.0, 400.0)))
    assert (r.w, r.h) == (150.0, 100.0) and r.center == (500.0, 400.0)


def test_radio_de_esquina_proporcional():
    assert lens_corner_radius(rounded(zoom=2.0)) == pytest.approx(80 * 0.12)


def test_crop_box_en_enteros():
    assert crop_box(rounded(source=Rect(10.4, 20.6, 50.0, 30.0))) == (10, 21, 60, 51)


def test_contains_in_lens_segun_la_forma():
    c = circle(center=(400.0, 300.0), zoom=2.0)  # radio 60
    assert contains_in_lens(c, (400.0, 300.0)) and contains_in_lens(c, (455.0, 300.0))
    assert not contains_in_lens(c, (459.0, 359.0))  # la esquina del cuadrado, fuera del circulo
    r = rounded(center=(400.0, 300.0), zoom=2.0)
    assert contains_in_lens(r, (459.0, 339.0))


def test_near_source_border():
    c = circle()  # centro (130,120), radio 30
    assert near_source_border(c, (130.0 + 30, 120.0), 5)
    assert not near_source_border(c, (130.0, 120.0), 5)
    r = rounded()
    assert near_source_border(r, (100.0, 120.0), 5)
    assert not near_source_border(r, (130.0, 120.0), 5)


# --- conector -------------------------------------------------------------

def test_conector_circular_son_dos_tangentes_perpendiculares_al_radio():
    m = circle(center=(400.0, 300.0))
    src, lens = effective_source(m), lens_rect(m)
    segments = connector_segments(m)
    assert len(segments) == 2
    for (p1, p2), (c, r) in zip(segments, [(src.center, src.w / 2)] * 2):
        # los extremos estan sobre cada circulo
        assert math.hypot(p1[0] - src.center[0], p1[1] - src.center[1]) == pytest.approx(src.w / 2)
        assert math.hypot(p2[0] - lens.center[0], p2[1] - lens.center[1]) == pytest.approx(lens.w / 2)
        # la tangente es perpendicular al radio en ambos puntos
        tx, ty = p2[0] - p1[0], p2[1] - p1[1]
        r1 = (p1[0] - src.center[0], p1[1] - src.center[1])
        r2 = (p2[0] - lens.center[0], p2[1] - lens.center[1])
        assert tx * r1[0] + ty * r1[1] == pytest.approx(0, abs=1e-6)
        assert tx * r2[0] + ty * r2[1] == pytest.approx(0, abs=1e-6)


def test_conector_circular_con_radios_iguales_son_paralelas():
    m = circle(zoom=1.0, center=(400.0, 120.0))
    (a1, b1), (a2, b2) = connector_segments(m)
    assert (b1[0] - a1[0], b1[1] - a1[1]) == pytest.approx((b2[0] - a2[0], b2[1] - a2[1]))


def test_conector_vacio_si_se_tocan_o_se_solapan_o_esta_apagado():
    assert connector_segments(circle(center=(140.0, 120.0))) == []
    assert connector_segments(circle(connector=False)) == []
    assert connector_segments(rounded(center=SRC.center)) == []


def test_conector_rectangular_une_los_bordes_sobre_la_linea_de_los_centros():
    m = rounded(center=(400.0, 120.0))  # a la derecha, misma altura; lente 120x80
    [(p1, p2)] = connector_segments(m)
    assert p1 == pytest.approx((160.0, 120.0))   # borde derecho del origen
    assert p2 == pytest.approx((340.0, 120.0))   # borde izquierdo del lente (400 - 60)


def test_conector_rectangular_en_diagonal_sale_por_el_borde_correcto():
    m = rounded(center=(400.0, 400.0))
    [(p1, p2)] = connector_segments(m)
    lens = lens_rect(m)
    on_src = p1[0] == pytest.approx(SRC.right) or p1[1] == pytest.approx(SRC.bottom)
    on_lens = p2[0] == pytest.approx(lens.x) or p2[1] == pytest.approx(lens.y)
    assert on_src and on_lens


# --- colocacion automatica -------------------------------------------------

def _no_cubre(source, zoom, shape, size, center):
    m = Magnifier("p", source, center, zoom, shape)
    return not lens_rect(m).intersects(effective_source(m))


def test_colocacion_nunca_cubre_el_origen_y_cabe_en_la_imagen():
    for shape in (LensShape.CIRCLE, LensShape.ROUNDED):
        c = default_lens_center(SRC, 2.0, shape, (1000, 600))
        m = Magnifier("p", SRC, c, 2.0, shape)
        lens = lens_rect(m)
        assert _no_cubre(SRC, 2.0, shape, (1000, 600), c)
        assert lens.x >= 0 and lens.y >= 0 and lens.right <= 1000 and lens.bottom <= 600


def test_colocacion_elige_el_lado_con_mas_espacio():
    pegado_izq = Rect(10, 280, 60, 40)
    c = default_lens_center(pegado_izq, 2.0, LensShape.ROUNDED, (1000, 600))
    assert c[0] > pegado_izq.right  # a la derecha
    pegado_der = Rect(930, 280, 60, 40)
    c = default_lens_center(pegado_der, 2.0, LensShape.ROUNDED, (1000, 600))
    assert c[0] < pegado_der.x  # a la izquierda


def test_colocacion_evita_obstaculos():
    origen = Rect(300, 250, 60, 40)
    obstaculo = Rect(360, 0, 200, 600)  # tapa el lado derecho
    c = default_lens_center(origen, 2.0, LensShape.ROUNDED, (1000, 600), obstacles=[obstaculo])
    lens = lens_rect(Magnifier("p", origen, c, 2.0, LensShape.ROUNDED))
    assert not lens.intersects(obstaculo) and not lens.intersects(origen)


def test_colocacion_sin_lugar_limpio_elige_el_que_menos_estorba_y_no_cubre_el_origen():
    obstaculo = Rect(160, 0, 400, 600)  # con el origen pegado a la esquina no cabe nada limpio
    c = default_lens_center(SRC, 2.0, LensShape.ROUNDED, (1000, 600), obstacles=[obstaculo])
    lens = lens_rect(Magnifier("p", SRC, c, 2.0, LensShape.ROUNDED))
    assert not lens.intersects(SRC)
    assert lens.x >= 0 and lens.y >= 0 and lens.right <= 1000 and lens.bottom <= 600


def test_colocacion_con_lente_mas_grande_que_la_imagen_no_truena():
    c = default_lens_center(Rect(10, 10, 80, 60), 8.0, LensShape.ROUNDED, (200, 150))
    assert isinstance(c[0], float) and isinstance(c[1], float)


def test_is_crowded_detecta_lente_encima_o_demasiado_cerca():
    assert lens_is_crowded(circle(center=SRC.center))                    # encima del origen
    cerca = Magnifier("l", Rect(100, 100, 60, 40), (195.0, 120.0), 1.0, LensShape.ROUNDED)  # lente 195..255: hueco de 5 px
    assert lens_is_crowded(cerca)
    bien = Magnifier("l", Rect(100, 100, 60, 40), (260.0, 120.0), 1.0, LensShape.ROUNDED)   # lente 230..290: hueco de 70 px
    assert not lens_is_crowded(bien)
