import pytest

from core.annotate import style
from core.annotate.edit import (
    Handle,
    clamp_point,
    distance_to_segment,
    find_index,
    hit_handle,
    hit_item,
    hit_test,
    item_handles,
    move_item,
    new_id,
    next_step_number,
    rect_from_points,
    resize_item,
    selection_rect,
)
from core.annotate.model import Arrow, Marker, Rect, Redaction, StepBadge, TextLabel
from core.annotate.primitives import label_box

M = Marker("m1", Rect(100, 100, 200, 100))
R = Redaction("r1", Rect(100, 100, 200, 100))
A = Arrow("a1", (0.0, 0.0), (100.0, 0.0))
S = StepBadge("s1", (50.0, 50.0), 1)
T = TextLabel("t1", (200.0, 200.0), "hola")


# --- ids y numeracion ------------------------------------------------------

def test_new_id_es_unico_y_sigue_la_secuencia():
    assert new_id([]) == "a1"
    assert new_id([Marker("a1", Rect(0, 0, 1, 1)), Marker("a7", Rect(0, 0, 1, 1))]) == "a8"
    assert new_id([Marker("m1", Rect(0, 0, 1, 1))]) == "a1"


def test_next_step_number_continua_la_numeracion():
    assert next_step_number([]) == 1
    assert next_step_number([StepBadge("s", (0.0, 0.0), 1), StepBadge("t", (0.0, 0.0), 4)]) == 5
    assert next_step_number([M]) == 1


def test_find_index():
    assert find_index([M, A], "a1") == 1
    assert find_index([M, A], "no") is None


# --- geometria auxiliar ----------------------------------------------------

def test_clamp_point():
    assert clamp_point((-5.0, 900.0), (100, 200)) == (0.0, 200.0)
    assert clamp_point((50.0, 50.0), (100, 200)) == (50.0, 50.0)


def test_distance_to_segment():
    assert distance_to_segment((50.0, 10.0), (0.0, 0.0), (100.0, 0.0)) == 10.0
    assert distance_to_segment((-30.0, 40.0), (0.0, 0.0), (100.0, 0.0)) == 50.0  # mide al extremo
    assert distance_to_segment((3.0, 4.0), (0.0, 0.0), (0.0, 0.0)) == 5.0  # segmento de largo cero


def test_rect_from_points_normaliza_cualquier_direccion():
    assert rect_from_points((10.0, 40.0), (30.0, 20.0)) == Rect(10, 20, 20, 20)


# --- hit-testing -----------------------------------------------------------

def test_marker_solo_se_selecciona_por_el_borde():
    assert hit_item(M, (100.0, 150.0), 5, 1.0)       # sobre el borde izquierdo
    assert hit_item(M, (97.0, 150.0), 5, 1.0)        # un poco afuera, dentro de la tolerancia
    assert not hit_item(M, (200.0, 150.0), 5, 1.0)   # el interior queda libre
    assert not hit_item(M, (50.0, 50.0), 5, 1.0)


def test_marker_chico_se_selecciona_completo():
    chico = Marker("m", Rect(100, 100, 6, 6))
    assert hit_item(chico, (103.0, 103.0), 5, 1.0)


def test_redaction_se_selecciona_por_dentro():
    assert hit_item(R, (200.0, 150.0), 5, 1.0)
    assert not hit_item(R, (400.0, 400.0), 5, 1.0)


def test_arrow_se_selecciona_cerca_de_la_linea():
    assert hit_item(A, (50.0, 4.0), 5, 1.0)
    assert not hit_item(A, (50.0, 30.0), 5, 1.0)


def test_step_usa_su_radio_escalado():
    assert hit_item(S, (50.0 + style.STEP_RADIUS, 50.0), 2, 1.0)
    assert not hit_item(S, (50.0 + style.STEP_RADIUS * 2, 50.0), 2, 1.0)
    assert hit_item(S, (50.0 + style.STEP_RADIUS * 2, 50.0), 2, 2.0)  # con escala 2 el circulo es el doble


def test_text_se_selecciona_dentro_de_su_caja():
    box = label_box(T, 1.0)
    assert hit_item(T, (box.x + box.w / 2, box.y + box.h / 2), 4, 1.0)
    assert not hit_item(T, (box.right + 50, box.bottom + 50), 4, 1.0)


def test_hit_test_gana_el_de_mas_arriba():
    abajo = Redaction("r", Rect(0, 0, 100, 100))
    arriba = Redaction("r2", Rect(0, 0, 100, 100))
    assert hit_test([abajo, arriba], (50.0, 50.0), 4, 1.0) == "r2"
    assert hit_test([abajo, arriba], (500.0, 500.0), 4, 1.0) is None


# --- asas ------------------------------------------------------------------

def test_item_handles_por_tipo():
    assert len(item_handles(M)) == 8 and len(item_handles(R)) == 8
    assert set(item_handles(A)) == {Handle.START, Handle.END}
    assert item_handles(S) == {} and item_handles(T) == {}


def test_hit_handle_elige_la_mas_cercana_dentro_de_la_tolerancia():
    assert hit_handle(M, (101.0, 101.0), 6) is Handle.NW
    assert hit_handle(M, (300.0, 150.0), 6) is Handle.E
    assert hit_handle(M, (200.0, 150.0), 6) is None
    assert hit_handle(A, (99.0, 1.0), 6) is Handle.END


# --- mover -----------------------------------------------------------------

@pytest.mark.parametrize("item", [M, R, A, S, T], ids=lambda i: type(i).__name__)
def test_move_item_desplaza_y_conserva_el_resto(item):
    moved = move_item(item, 10.0, -5.0)
    assert moved.id == item.id and moved != item
    assert move_item(moved, -10.0, 5.0) == item


def test_move_item_rect_y_flecha():
    assert move_item(M, 10, 20).rect == Rect(110, 120, 200, 100)
    assert move_item(A, 5, 5).start == (5.0, 5.0) and move_item(A, 5, 5).end == (105.0, 5.0)


# --- redimensionar ---------------------------------------------------------

def test_resize_esquina_mueve_dos_lados():
    assert resize_item(M, Handle.SE, (350.0, 260.0)).rect == Rect(100, 100, 250, 160)
    assert resize_item(M, Handle.NW, (80.0, 90.0)).rect == Rect(80, 90, 220, 110)


def test_resize_borde_mueve_un_solo_lado():
    assert resize_item(M, Handle.E, (400.0, 999.0)).rect == Rect(100, 100, 300, 100)
    assert resize_item(M, Handle.N, (999.0, 50.0)).rect == Rect(100, 50, 200, 150)


def test_resize_nunca_baja_del_tamano_minimo():
    chico = resize_item(M, Handle.E, (50.0, 150.0), min_size=10).rect
    assert chico.w == 10 and chico.x == 100
    chico = resize_item(M, Handle.W, (900.0, 150.0), min_size=10).rect
    assert chico.w == 10 and chico.right == 300
    chico = resize_item(M, Handle.N, (150.0, 900.0), min_size=10).rect
    assert chico.h == 10 and chico.bottom == 200


def test_resize_flecha_mueve_un_extremo():
    assert resize_item(A, Handle.END, (10.0, 20.0)).end == (10.0, 20.0)
    assert resize_item(A, Handle.START, (10.0, 20.0)).start == (10.0, 20.0)
    assert resize_item(A, Handle.START, (10.0, 20.0)).end == A.end


def test_resize_de_tipos_sin_asas_no_hace_nada():
    assert resize_item(S, Handle.E, (999.0, 999.0)) == S
    assert resize_item(T, Handle.E, (999.0, 999.0)) == T


def test_selection_rect_por_tipo():
    assert selection_rect(M, 1.0) == M.rect
    assert selection_rect(A, 1.0) == Rect(0, 0, 100, 0)
    assert selection_rect(S, 1.0) == Rect(30, 30, 40, 40)
    assert selection_rect(T, 1.0) == label_box(T, 1.0)
