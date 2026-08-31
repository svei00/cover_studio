import pytest

from core.easing import (
    DEFAULT_OVERSHOOT,
    EASING_BY_NAME,
    PENNER_OVERSHOOT,
    Easing,
    clamp01,
    ease_in_out_cubic,
    ease_out_back,
    ease_out_cubic,
    ease_out_elastic,
    get_easing,
    lerp,
)

SAMPLES = [i / 1000 for i in range(1001)]
MONOTONIC = [e for e in Easing if e not in (Easing.OUT_BACK, Easing.OUT_ELASTIC)]


def test_clamp01_y_lerp():
    assert (clamp01(-0.5), clamp01(0.3), clamp01(7.0)) == (0.0, 0.3, 1.0)
    assert lerp(10.0, 20.0, 0.0) == 10.0 and lerp(10.0, 20.0, 1.0) == 20.0 and lerp(10.0, 20.0, 0.25) == 12.5
    assert lerp(0.0, 10.0, 1.5) == 15.0  # no acota: lo decide quien llama


def test_todas_las_curvas_estan_registradas():
    assert set(EASING_BY_NAME) == set(Easing)


@pytest.mark.parametrize("easing", list(Easing))
def test_empiezan_en_0_y_terminan_en_1(easing):
    f = get_easing(easing)
    assert f(0.0) == 0.0  # exacto, no -1e-16
    assert f(1.0) == 1.0


@pytest.mark.parametrize("easing", list(Easing))
def test_la_entrada_fuera_de_rango_se_acota(easing):
    f = get_easing(easing)
    assert f(-0.5) == f(0.0) == 0.0
    assert f(1.7) == f(1.0) == 1.0


@pytest.mark.parametrize("easing", MONOTONIC)
def test_las_curvas_sin_rebote_nunca_retroceden_ni_pasan_de_1(easing):
    f = get_easing(easing)
    values = [f(t) for t in SAMPLES]
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))
    assert max(values) <= 1.0 + 1e-12 and min(values) >= 0.0


def test_las_out_arrancan_rapido_y_asientan():
    for easing in (Easing.OUT_QUAD, Easing.OUT_CUBIC, Easing.OUT_QUINT, Easing.OUT_EXPO):
        f = get_easing(easing)
        assert f(0.5) > 0.5, easing  # a mitad de tiempo ya pasaron de la mitad del recorrido


def test_in_out_cubic_es_simetrica():
    assert ease_in_out_cubic(0.5) == pytest.approx(0.5)
    assert ease_in_out_cubic(0.25) + ease_in_out_cubic(0.75) == pytest.approx(1.0)


def test_out_back_rebasa_1_y_regresa():
    values = [ease_out_back(t) for t in SAMPLES]
    assert max(values) > 1.0
    assert values[-1] == 1.0  # termina asentado, no en el pico


def test_rebase_medido_de_out_back():
    def rebase(s):
        return max(ease_out_back(t, s) for t in SAMPLES) - 1.0

    assert rebase(0.6) == pytest.approx(0.0125, abs=0.001)
    assert rebase(DEFAULT_OVERSHOOT) == pytest.approx(0.037, abs=0.002)  # el "slight" por defecto
    assert rebase(PENNER_OVERSHOOT) == pytest.approx(0.10, abs=0.002)    # el valor clasico de Penner


def test_out_back_con_overshoot_0_es_out_cubic():
    assert all(ease_out_back(t, 0.0) == pytest.approx(ease_out_cubic(t)) for t in SAMPLES)


def test_mas_overshoot_rebasa_mas():
    picos = [max(ease_out_back(t, s) for t in SAMPLES) for s in (0.0, 0.5, 1.0, 2.0)]
    assert picos == sorted(picos) and len(set(picos)) == 4


def test_out_elastic_oscila_pero_acotada():
    values = [ease_out_elastic(t) for t in SAMPLES]
    assert max(values) == pytest.approx(1.373, abs=0.01)
    assert min(values) >= -0.01
    # cruza el 1.0 varias veces (en 0.075, 0.225, 0.375...): de verdad rebota. Algunas muestras
    # caen justo en 1.0, asi que se cuentan los cambios de signo ignorando esos ceros.
    signos = [1 if v > 1.0 else -1 for v in values if abs(v - 1.0) > 1e-9]
    cruces = sum(1 for a, b in zip(signos, signos[1:]) if a != b)
    assert cruces >= 3


def test_get_easing_acepta_el_enum_y_el_texto():
    assert get_easing(Easing.OUT_CUBIC) is get_easing("out-cubic") is ease_out_cubic


def test_get_easing_desconocido_lanza_error_con_las_opciones():
    with pytest.raises(ValueError) as exc:
        get_easing("basura")
    assert "basura" in str(exc.value) and "out-cubic" in str(exc.value)
