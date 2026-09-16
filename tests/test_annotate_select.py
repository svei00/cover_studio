from core.annotate import edit
from core.annotate.model import Arrow, ArrowSide, Marker, Rect, StepBadge

M = Marker("m", Rect(100, 100, 200, 80), ArrowSide.RIGHT)
ARROWS = {"m": ((390.0, 140.0), (306.0, 140.0))}   # inicio y punta de la flecha, a la derecha del marcador


def test_el_borde_del_marcador_lo_selecciona():
    assert edit.hit_test([M], (100, 140), 4, 1.0) == "m"


def test_el_interior_del_marcador_lo_selecciona_si_no_hay_nada_mas():
    assert edit.hit_test([M], (200, 140), 4, 1.0) == "m"
    assert edit.hit_test([M], (500, 400), 4, 1.0) is None   # fuera de todo


def test_lo_que_esta_dentro_del_marcador_gana_sobre_su_interior():
    paso = StepBadge("s", (200.0, 140.0), 1)
    assert edit.hit_test([M, paso], (200, 140), 4, 1.0) == "s"      # el paso, aunque se dibujo despues
    assert edit.hit_test([paso, M], (200, 140), 4, 1.0) == "s"      # y tambien si el marcador va encima
    assert edit.hit_test([M, paso], (150, 120), 4, 1.0) == "m"      # el resto del interior es del marcador


def test_la_flecha_del_marcador_lo_selecciona():
    assert edit.hit_test([M], (340, 140), 4, 1.0) is None            # sin saber donde esta la flecha
    assert edit.hit_test([M], (340, 140), 4, 1.0, ARROWS) == "m"
    assert edit.hit_test([M], (340, 160), 4, 1.0, ARROWS) is None    # lejos de la flecha


def test_otras_anotaciones_siguen_igual():
    flecha = Arrow("a", (0.0, 0.0), (100.0, 0.0))
    assert edit.hit_test([flecha], (50, 2), 4, 1.0) == "a"
    assert edit.hit_test([flecha], (50, 20), 4, 1.0) is None
