from pathlib import Path

import pytest

from core.annotate import style
from core.annotate.model import (
    AnnotationDoc,
    Arrow,
    ArrowSide,
    Marker,
    Rect,
    Redaction,
    StepBadge,
    TextAlign,
    TextLabel,
    text_label_from_preset,
)
from core.annotate.primitives import (
    PCircle,
    PLine,
    PPolygon,
    PRect,
    PText,
    build_primitives,
    label_box,
    marker_primitives,
    resolve_arrow_side,
    step_primitives,
    text_label_primitives,
)

MARKER = Marker("m1", Rect(100, 100, 200, 50))


def _red_lines(prims):
    return [p for p in prims if isinstance(p, PLine) and p.stroke == style.RED]


def _red_heads(prims):
    return [p for p in prims if isinstance(p, PPolygon) and p.fill == style.RED]


def _rounded(points):
    return sorted((round(x, 2), round(y, 2)) for x, y in points)


def test_marker_flecha_izquierda_coincide_con_el_builder():
    prims = marker_primitives(MARKER, 1.0, ArrowSide.LEFT)
    line = _red_lines(prims)[0]
    assert line.a == (22.0, 125.0)
    assert line.b == (94.0, 125.0)
    assert line.width == 5.0
    head = _red_heads(prims)[0]
    expected = [(94.0, 125.0), (94 - 16.9, 125 - 10.4), (94 - 16.9, 125 + 10.4)]
    assert _rounded(head.points) == _rounded(expected)


def test_marker_flecha_derecha_arriba_y_abajo():
    right = _red_lines(marker_primitives(MARKER, 1.0, ArrowSide.RIGHT))[0]
    assert right.b == (306.0, 125.0) and right.a == (378.0, 125.0)
    top = _red_lines(marker_primitives(MARKER, 1.0, ArrowSide.TOP))[0]
    assert top.b == (200.0, 94.0) and top.a == (200.0, 22.0)
    bottom = _red_lines(marker_primitives(MARKER, 1.0, ArrowSide.BOTTOM))[0]
    assert bottom.b == (200.0, 156.0) and bottom.a == (200.0, 228.0)


def test_marker_resplandor_tiene_nueve_anillos_con_la_formula_del_builder():
    prims = marker_primitives(MARKER, 1.0, ArrowSide.NONE)
    rings = [p for p in prims if isinstance(p, PRect) and p.stroke == style.GLOW_GOLD]
    assert len(rings) == 9
    first = rings[0]
    assert first.rect == Rect(100 - 2.2, 100 - 2.2, 200 + 4.4, 50 + 4.4)
    assert first.opacity == round(0.55 * (1 - 0.1) ** 1.6, 4)
    assert first.rx == pytest.approx(6 + 2.2)
    assert first.width == 4.5


def test_marker_sin_glow_solo_dibuja_recuadro_y_flecha():
    m = Marker("m", Rect(100, 100, 200, 50), glow=False)
    prims = marker_primitives(m, 1.0, ArrowSide.LEFT)
    assert not any(getattr(p, "stroke", None) == style.GLOW_GOLD for p in prims)
    assert any(isinstance(p, PRect) and p.stroke == style.RED for p in prims)


def test_marker_sin_flecha_no_dibuja_lineas():
    prims = marker_primitives(MARKER, 1.0, ArrowSide.NONE)
    assert not any(isinstance(p, PLine) for p in prims)


def test_escala_duplica_grosores_y_largos():
    line = _red_lines(marker_primitives(MARKER, 2.0, ArrowSide.LEFT))[0]
    assert line.width == 10.0
    assert line.b[0] - line.a[0] == 144.0


def test_marker_con_lado_auto_sin_resolver_lanza_error():
    with pytest.raises(ValueError):
        marker_primitives(MARKER, 1.0, ArrowSide.AUTO)


def test_arrow_suelta_apunta_a_end():
    a = Arrow("a", (0.0, 0.0), (100.0, 0.0))
    line = _red_lines(build_primitives(AnnotationDoc(Path("x.png"), (800, 600), [a])))[0]
    assert line.a == (0.0, 0.0) and line.b == (100.0, 0.0)


def test_arrow_de_largo_cero_no_dibuja_nada():
    a = Arrow("a", (5.0, 5.0), (5.0, 5.0))
    assert build_primitives(AnnotationDoc(Path("x.png"), (800, 600), [a])) == []


def test_resolve_arrow_side_respeta_el_lado_explicito():
    m = Marker("m", Rect(100, 100, 50, 50), arrow=ArrowSide.BOTTOM)
    assert resolve_arrow_side(m, (800, 600), [m], 1.0) is ArrowSide.BOTTOM


def test_resolve_arrow_side_nunca_apunta_hacia_afuera_de_la_imagen():
    pegado_izq = Marker("m", Rect(5, 250, 100, 50))
    assert resolve_arrow_side(pegado_izq, (1000, 600), [pegado_izq], 1.0) is not ArrowSide.LEFT
    pegado_arriba = Marker("m", Rect(450, 5, 100, 50))
    assert resolve_arrow_side(pegado_arriba, (1000, 600), [pegado_arriba], 1.0) is not ArrowSide.TOP


def test_resolve_arrow_side_evita_pasar_sobre_otra_anotacion():
    m = Marker("m", Rect(400, 250, 100, 50))
    tapa_izquierda = Marker("o", Rect(250, 240, 120, 70), arrow=ArrowSide.NONE)
    side = resolve_arrow_side(m, (1000, 600), [m, tapa_izquierda], 1.0)
    assert side is not ArrowSide.LEFT


def test_step_badge_dibuja_circulo_y_numero():
    prims = step_primitives(StepBadge("s", (50.0, 60.0), 3), 1.0)
    circle = next(p for p in prims if isinstance(p, PCircle))
    assert circle.r == 20.0 and circle.stroke == style.GOLD and circle.fill == style.CARD_FILL
    assert next(p for p in prims if isinstance(p, PText)).text == "3"


def test_redaction_no_genera_primitivas():
    doc = AnnotationDoc(Path("x.png"), (800, 600), [Redaction("r", Rect(0, 0, 50, 50))])
    assert build_primitives(doc) == []


def test_auto_scale():
    assert style.auto_scale(1600) == 1.0
    assert style.auto_scale(3200) == 2.0
    assert style.auto_scale(100) == style.MIN_SCALE
    assert style.auto_scale(99999) == style.MAX_SCALE


def test_doc_usa_style_scale_explicito_o_automatico():
    m = Marker("m", Rect(400, 250, 100, 50), arrow=ArrowSide.LEFT)
    auto = AnnotationDoc(Path("x.png"), (3200, 2000), [m])
    fijo = AnnotationDoc(Path("x.png"), (3200, 2000), [m], style_scale=1.0)
    assert _red_lines(build_primitives(auto))[0].width == 10.0
    assert _red_lines(build_primitives(fijo))[0].width == 5.0


# --- etiquetas de texto --------------------------------------------------

def test_text_label_con_fondo_dibuja_caja_y_texto():
    t = text_label_from_preset("t", (10.0, 20.0), "Aqui falla", "nota")
    prims = text_label_primitives(t, 1.0)
    bg = prims[0]
    assert isinstance(bg, PRect) and bg.fill == style.CARD_FILL and bg.stroke == style.TAN
    assert bg.fill_opacity == 0.92
    texts = [p for p in prims if isinstance(p, PText)]
    assert [x.text for x in texts] == ["Aqui falla"]
    assert texts[0].outline is None


def test_text_label_libre_no_tiene_caja_y_si_contorno():
    t = text_label_from_preset("t", (10.0, 20.0), "Suelto", "libre")
    prims = text_label_primitives(t, 1.0)
    assert not any(isinstance(p, PRect) for p in prims)
    assert prims[0].outline == style.PAGE_BG and prims[0].outline_width >= 2.0


def test_text_label_multilinea_una_primitiva_por_linea_y_caja_mas_alta():
    una = TextLabel("t", (0.0, 0.0), "uno")
    dos = TextLabel("t", (0.0, 0.0), "uno\ndos")
    assert label_box(dos, 1.0).h > label_box(una, 1.0).h
    texts = [p for p in text_label_primitives(dos, 1.0) if isinstance(p, PText)]
    assert [p.text for p in texts] == ["uno", "dos"]
    assert texts[1].pos[1] > texts[0].pos[1]


def test_text_label_lineas_vacias_se_omiten():
    t = TextLabel("t", (0.0, 0.0), "a\n\nb")
    texts = [p for p in text_label_primitives(t, 1.0) if isinstance(p, PText)]
    assert [p.text for p in texts] == ["a", "b"]


def test_text_label_la_caja_contiene_el_texto_con_padding():
    t = TextLabel("t", (100.0, 100.0), "Hola mundo", size=30.0, padding=10.0)
    box = label_box(t, 1.0)
    assert box.x == 100.0 and box.y == 100.0
    assert box.w > 20.0 and box.h == pytest.approx(30 * style.TEXT_LINE_HEIGHT + 20)


def test_text_label_centrada_ancla_en_el_centro_de_la_caja():
    t = TextLabel("t", (0.0, 0.0), "Hola", align=TextAlign.CENTER)
    box = label_box(t, 1.0)
    text = next(p for p in text_label_primitives(t, 1.0) if isinstance(p, PText))
    assert text.anchor == "middle" and text.pos[0] == pytest.approx(box.w / 2)


def test_text_label_escala():
    t = TextLabel("t", (0.0, 0.0), "Hola")
    assert label_box(t, 2.0).h == pytest.approx(2 * label_box(t, 1.0).h)


def test_text_label_preset_desconocido_lanza_error():
    with pytest.raises(ValueError):
        text_label_from_preset("t", (0.0, 0.0), "x", "no-existe")


def test_presets_de_texto_usan_la_paleta_de_marca():
    exito = text_label_from_preset("t", (0.0, 0.0), "ok", "exito")
    assert exito.bg == style.SUCCESS_FILL and exito.border == style.SUCCESS_GREEN
    alerta = text_label_from_preset("t", (0.0, 0.0), "!", "alerta")
    assert alerta.border == style.RED and alerta.bg == style.CARD_FILL


def test_build_primitives_respeta_el_orden_de_dibujo():
    items = [
        StepBadge("s", (500.0, 500.0), 1),
        TextLabel("t", (10.0, 10.0), "x", bg=None, border=None),
    ]
    prims = build_primitives(AnnotationDoc(Path("x.png"), (1600, 900), items))
    assert isinstance(prims[0], PCircle)
    assert isinstance(prims[-1], PText)
