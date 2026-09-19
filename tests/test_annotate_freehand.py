import math
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from core.annotate import edit, freehand, style
from core.annotate.bounds import required_padding
from core.annotate.errors import AnnotateError
from core.annotate.io import item_from_dict, item_to_dict, load_doc, save_doc
from core.annotate.model import AnnotationDoc, PenMode, Stroke
from core.annotate.palette import BRAND_PALETTE, PALETTE_LABELS, Palette, palette_from_dict, palette_to_dict
from core.annotate.primitives import PPolyline, stroke_curve, stroke_primitives
from core.annotate.svg import export_png, primitive_to_svg

S = Stroke("s", ((100.0, 100.0), (150.0, 130.0), (200.0, 100.0)))


# --- algoritmos puros ----------------------------------------------------------------------------

def test_longitud_y_cuando_agregar_un_punto():
    assert freehand.path_length([(0, 0), (3, 4), (3, 10)]) == 11.0
    assert freehand.path_length([(5, 5)]) == 0.0
    assert freehand.should_add([], (1, 1))
    assert not freehand.should_add([(0, 0)], (0.5, 0.5))
    assert freehand.should_add([(0, 0)], (1.0, 0.0))


def test_suavizar_conserva_los_extremos_y_quita_el_temblor():
    rng = random.Random(3)
    ruidosa = [(x, 50 + rng.uniform(-2, 2)) for x in range(0, 200, 2)]
    suave = freehand.smooth(ruidosa)
    assert suave[0] == ruidosa[0] and suave[-1] == ruidosa[-1]
    desviacion = lambda pts: max(abs(y - 50) for _, y in pts[2:-2])  # noqa: E731
    assert desviacion(suave) < desviacion(ruidosa) * 0.6
    assert freehand.smooth([(0, 0), (1, 1)]) == [(0, 0), (1, 1)]          # con menos de 3 puntos no hay que suavizar


def test_simplificar_quita_los_puntos_colineales_y_conserva_las_esquinas():
    recta = [(x, 2 * x) for x in range(0, 100)]
    assert freehand.simplify(recta, 0.5) == [(0, 0), (99, 198)]
    codo = [(x, 0) for x in range(50)] + [(49, y) for y in range(1, 50)]
    simple = freehand.simplify(codo, 0.5)
    assert (49, 0) in simple and simple[0] == (0, 0) and simple[-1] == (49, 49) and len(simple) == 3


def test_simplificar_respeta_la_tolerancia():
    rng = random.Random(5)
    pts = [(x, 30 * math.sin(x / 15) + rng.uniform(-0.3, 0.3)) for x in range(0, 300)]
    tol = 1.0
    simple = freehand.simplify(pts, tol)
    assert len(simple) < len(pts) / 4
    for p in pts:   # todo punto original queda a menos de la tolerancia de la recta simplificada
        assert freehand.distance_to_polyline(p, simple) <= tol + 1e-9


def test_simplificar_un_trazo_enorme_no_agota_la_recursion_ni_tarda():
    pts = [(i * 0.1, math.sin(i * 0.01) * 50) for i in range(40000)]
    inicio = time.perf_counter()
    assert len(freehand.simplify(pts, 0.5)) > 10
    assert time.perf_counter() - inicio < 5.0


def test_un_circulo_dibujado_a_mano_queda_en_pocos_puntos_y_dentro_de_un_pixel_y_medio():
    rng = random.Random(7)
    crudos = []
    for i in range(0, 721):          # una vuelta con 721 puntos del mouse y un poco de temblor
        a = math.radians(i / 2)
        r = 100 + rng.uniform(-0.8, 0.8)
        crudos.append((300 + r * math.cos(a), 300 + r * math.sin(a)))
    control = freehand.process(crudos)
    assert len(control) < len(crudos) / 5                               # mucho mas ligero
    curva = freehand.flatten(control)
    errores = [abs(math.dist((300, 300), p) - 100) for p in curva]
    assert max(errores) < 1.6 and sum(errores) / len(errores) < 0.7     # medido, no supuesto


def test_process_redondea_a_centesimas_y_tope_de_puntos():
    assert freehand.process([(0.123456, 1.987654)]) == ((0.12, 1.99),)
    pts = [(i, (i % 7) * 3.0) for i in range(20000)]
    assert len(freehand.process(pts, tolerance=0.0)) <= freehand.MAX_POINTS


def test_la_curva_pasa_por_los_puntos_de_control_y_es_pareja():
    control = [(0, 0), (50, 40), (100, 0), (150, 40), (200, 0)]
    curva = freehand.flatten(control)
    assert curva[0] == control[0] and curva[-1] == control[-1]
    for c in control:
        assert min(math.dist(c, q) for q in curva) < 0.5
    assert all(math.dist(a, b) <= freehand.SAMPLE_SPACING * 1.2 for a, b in zip(curva, curva[1:]))
    assert all(math.isfinite(x) and math.isfinite(y) for x, y in curva)


def test_curva_de_uno_dos_puntos_o_con_repetidos():
    assert freehand.flatten([(5, 5)]) == [(5, 5)]
    assert freehand.flatten([(0, 0), (10, 10)]) == [(0, 0), (10, 10)]
    repetidos = freehand.flatten([(0, 0), (0, 0), (10, 0), (10, 0), (20, 5)])
    assert all(math.isfinite(x) and math.isfinite(y) for x, y in repetidos)


def test_la_curva_no_da_lazos_en_un_giro_cerrado():
    control = [(0, 0), (100, 0), (100, 5), (0, 5)]          # un giro de 180 grados muy cerrado
    curva = freehand.flatten(control)
    assert max(y for _, y in curva) < 12 and min(y for _, y in curva) > -6   # el centripeto no se sale ni hace picos


def test_caja_y_distancia_a_la_polilinea():
    assert freehand.bounding_box([(10, 20), (30, 5), (25, 40)]) == (10, 5, 20, 35)
    assert freehand.distance_to_polyline((5, 5), [(0, 0), (10, 0)]) == 5.0
    assert freehand.distance_to_polyline((0, 3), [(0, 0)]) == 3.0
    assert freehand.distance_to_polyline((0, 0), []) == math.inf


# --- modelo, paleta y primitivas -------------------------------------------------------------------

def test_el_trazo_por_defecto_es_un_lapiz_opaco_de_4_px():
    assert (S.mode, S.width, S.opacity, S.glow, S.color) == (PenMode.PEN, 4.0, 1.0, False, None)


def test_la_paleta_tiene_el_color_del_lapiz_y_un_proyecto_viejo_abre_igual():
    assert BRAND_PALETTE.pen == style.RED and PALETTE_LABELS["pen"] == "Lapiz"
    viejo = palette_to_dict(BRAND_PALETTE)
    del viejo["pen"]
    assert palette_from_dict(viejo).pen == style.RED


def test_lapiz_usa_el_color_de_su_paleta_y_el_resaltador_el_amarillo():
    (lapiz,) = stroke_primitives(S, 1.0)
    assert isinstance(lapiz, PPolyline) and lapiz.stroke == style.RED and lapiz.width == 4.0 and lapiz.blend is None
    (marcador,) = stroke_primitives(replace(S, mode=PenMode.MARKER, width=22.0), 1.0)
    assert marcador.stroke == style.HIGHLIGHT_YELLOW and marcador.blend == "multiply" and marcador.width == 22.0
    (translucido,) = stroke_primitives(replace(S, mode=PenMode.OVERLAY, opacity=0.5), 1.0)
    assert translucido.blend is None and translucido.opacity == 0.5 and translucido.stroke == style.HIGHLIGHT_YELLOW


def test_color_propio_paleta_del_documento_y_escala_de_trazo():
    assert stroke_primitives(replace(S, color="#112233"), 1.0)[0].stroke == "#112233"
    assert stroke_primitives(S, 1.0, Palette(pen="#445566"))[0].stroke == "#445566"
    assert stroke_primitives(S, 2.5)[0].width == 10.0


def test_la_polilinea_es_la_curva_del_trazo():
    assert stroke_primitives(S, 1.0)[0].points == stroke_curve(S)
    assert stroke_curve(S)[0] == S.points[0] and stroke_curve(S)[-1] == S.points[-1]


def test_un_trazo_sin_puntos_no_dibuja_y_uno_de_un_punto_es_un_punto():
    assert stroke_primitives(Stroke("v", ()), 1.0) == []
    (punto,) = stroke_primitives(Stroke("p", ((50.0, 60.0),)), 1.0)
    assert len(punto.points) == 2 and math.dist(*punto.points) < 0.05    # un segmento diminuto con remate redondo


def test_el_resplandor_es_un_halo_de_capas_debajo_del_trazo():
    prims = stroke_primitives(replace(S, glow=True), 1.0)
    assert len(prims) == len(style.GLOW_RINGS) + 1 and prims[-1].stroke == style.RED
    halo = prims[:-1]
    assert all(p.stroke == style.GLOW_GOLD for p in halo)
    anchos = [p.width for p in halo]
    assert anchos == sorted(anchos, reverse=True) and anchos[0] > S.width + 30   # el alcance de los demas resplandores
    assert stroke_primitives(replace(S, glow=True, glow_color="#AABBCC"), 1.0)[0].stroke == "#AABBCC"


def test_el_resplandor_del_trazo_pide_margen_en_el_borde():
    cerca = Stroke("c", ((2.0, 100.0), (2.0, 160.0)), glow=True)
    doc = AnnotationDoc(Path("x.png"), (400, 300), [cerca], style_scale=1.0)
    assert required_padding(doc) > required_padding(AnnotationDoc(Path("x.png"), (400, 300), [replace(cerca, glow=False)], style_scale=1.0))


# --- SVG y pixeles --------------------------------------------------------------------------------------

def test_svg_de_la_polilinea():
    svg = primitive_to_svg(stroke_primitives(S, 1.0)[0])
    assert svg.startswith("<polyline points=") and 'stroke="#621132"' in svg and 'stroke-width="4.00"' in svg
    assert 'fill="none"' in svg and 'stroke-linecap="round"' in svg and 'stroke-linejoin="round"' in svg
    assert 'stroke-opacity="1.00"' in svg and "mix-blend-mode" not in svg
    multiplicar = primitive_to_svg(stroke_primitives(replace(S, mode=PenMode.MARKER), 1.0)[0])
    assert 'style="mix-blend-mode:multiply"' in multiplicar
    assert 'stroke-opacity="0.50"' in primitive_to_svg(stroke_primitives(replace(S, opacity=0.5), 1.0)[0])


def _export(tmp_path, stroke, fondo=(255, 255, 255), size=(400, 300)):
    Image.new("RGB", size, fondo).save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", size, [stroke], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    return Image.open(tmp_path / "o.png").convert("RGB")


def _cerca(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_el_lapiz_se_exporta_con_su_color_y_el_grosor_y_el_fondo_queda_intacto(tmp_path):
    horizontal = Stroke("h", ((50.0, 150.0), (350.0, 150.0)), color="#FF0000", width=10.0)
    img = _export(tmp_path, horizontal)
    assert _cerca(img.getpixel((200, 150)), (255, 0, 0), 2)
    assert _cerca(img.getpixel((200, 146)), (255, 0, 0), 2) and img.getpixel((200, 160)) == (255, 255, 255)   # grosor de 10 px
    assert img.getpixel((20, 150)) == (255, 255, 255) and img.getpixel((200, 100)) == (255, 255, 255)


def test_el_resaltador_deja_el_texto_negro_y_en_fondo_oscuro_casi_no_se_ve(tmp_path):
    trazo = Stroke("m", ((50.0, 150.0), (350.0, 150.0)), color="#FFF200", mode=PenMode.MARKER, width=40.0)
    claro = Image.new("RGB", (400, 300), (255, 255, 255))
    claro.paste((0, 0, 0), (180, 140, 220, 160))                          # un "texto" negro bajo el trazo
    claro.save(tmp_path / "c.png")
    doc = AnnotationDoc(tmp_path / "c.png", (400, 300), [trazo], style_scale=1.0)
    export_png(doc, tmp_path / "o.png")
    img = Image.open(tmp_path / "o.png").convert("RGB")
    assert _cerca(img.getpixel((100, 150)), (255, 242, 0), 3)             # amarillo puro sobre blanco
    assert img.getpixel((200, 150)) == (0, 0, 0)                            # el texto negro sigue negro
    oscuro = _export(tmp_path, trazo, fondo=(32, 32, 32))
    assert max(oscuro.getpixel((100, 150))) < 40                           # sobre oscuro casi no se ve (por eso existe el translucido)


def test_el_resaltador_translucido_si_se_ve_sobre_oscuro(tmp_path):
    trazo = Stroke("t", ((50.0, 150.0), (350.0, 150.0)), color="#FFF200", mode=PenMode.OVERLAY, width=40.0, opacity=0.5)
    px = _export(tmp_path, trazo, fondo=(32, 32, 32)).getpixel((200, 150))
    assert px[0] > 120 and px[1] > 120 and px[2] < 40


def test_un_trazo_translucido_no_se_oscurece_donde_se_cruza_consigo_mismo(tmp_path):
    cruce = Stroke("x", ((50.0, 100.0), (350.0, 200.0), (350.0, 100.0), (50.0, 200.0)), color="#0000FF", width=30.0,
                   mode=PenMode.OVERLAY, opacity=0.5)
    img = _export(tmp_path, cruce)
    assert _cerca(img.getpixel((200, 150)), img.getpixel((120, 124)), 4)    # el cruce se ve igual que el resto del trazo


def test_el_pintor_de_qt_dibuja_el_trazo_igual_que_resvg(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage, QPainter

    from ui.annotate.painter import paint_primitives

    casos = [
        Stroke("a", ((50.0, 150.0), (350.0, 150.0)), color="#FF0000", width=12.0),
        Stroke("b", ((50.0, 150.0), (350.0, 150.0)), color="#FFF200", mode=PenMode.MARKER, width=30.0),
        Stroke("c", ((50.0, 150.0), (350.0, 150.0)), color="#0000FF", mode=PenMode.OVERLAY, opacity=0.4, width=30.0),
    ]
    for caso in casos:
        resvg = _export(tmp_path, caso).getpixel((200, 150))
        img = QImage(400, 300, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        paint_primitives(painter, stroke_primitives(caso, 1.0))
        painter.end()
        qt = QColor(img.pixel(200, 150))
        assert _cerca((qt.red(), qt.green(), qt.blue()), resvg, 4), (caso.mode, resvg, (qt.red(), qt.green(), qt.blue()))


# --- edicion ---------------------------------------------------------------------------------------------

def test_clic_sobre_el_trazo_lo_selecciona_y_lejos_no():
    assert edit.hit_test([S], (150, 130), 4, 1.0) == "s"
    assert edit.hit_test([S], (150, 134), 4, 1.0) == "s"          # dentro del grosor mas la tolerancia
    assert edit.hit_test([S], (150, 200), 4, 1.0) is None
    grueso = replace(S, width=40.0)
    assert edit.hit_test([grueso], (150, 148), 4, 1.0) == "s"     # un resaltador ancho se agarra por todo su ancho


def test_mover_el_trazo_traslada_todos_los_puntos():
    movido = edit.move_item(S, 10, -5)
    assert movido.points == tuple((x + 10, y - 5) for x, y in S.points) and movido.width == S.width


def test_las_asas_son_las_de_la_caja_y_escalan_el_trazo():
    assert len(edit.item_handles(S)) == 8
    escalado = edit.resize_item(S, edit.Handle.SE, (300.0, 160.0))      # la caja de (100,100)-(200,130) pasa a (100,100)-(300,160)
    xs, ys = [p[0] for p in escalado.points], [p[1] for p in escalado.points]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((100, 300, 100, 160))
    assert escalado.width == S.width
    assert escalado.points[1] == pytest.approx((200.0, 100.0 + 30 * 2))  # el punto medio escala en los dos ejes


def test_un_trazo_recto_sin_alto_tambien_se_puede_escalar():
    recto = Stroke("r", ((100.0, 100.0), (200.0, 100.0)))                # caja de alto 0
    ancho = edit.resize_item(recto, edit.Handle.E, (300.0, 100.0))
    assert [p[0] for p in ancho.points] == pytest.approx([100.0, 300.0]) and all(p[1] == pytest.approx(100.0) for p in ancho.points)


def test_la_caja_de_seleccion_incluye_el_grosor_y_un_trazo_vacio_no_rompe():
    assert edit.selection_rect(S, 1.0) == edit._stroke_box(S).inflate(2.0)
    vacio = Stroke("v", ())
    assert edit.item_handles(vacio) == {} and edit.selection_rect(vacio, 1.0).w == 0
    assert edit.resize_item(vacio, edit.Handle.E, (5, 5)) == vacio


# --- archivo ----------------------------------------------------------------------------------------------

def test_el_trazo_se_guarda_y_se_recupera(tmp_path):
    t = Stroke("s", ((1.5, 2.25), (30.0, 40.0), (60.0, 5.0)), "#123456", PenMode.OVERLAY, 22.0, 0.4, True, "#AABBCC")
    assert item_from_dict(item_to_dict(t)) == t
    img = tmp_path / "c.png"
    Image.new("RGB", (100, 100)).save(img)
    assert load_doc(save_doc(AnnotationDoc(img, (100, 100), [t]))).items == [t]


@pytest.mark.parametrize("key,bad,field,expected", [
    ("mode", "raro", "mode", PenMode.PEN), ("width", 0, "width", 4.0), ("width", 999, "width", 4.0),
    ("width", "x", "width", 4.0), ("opacity", 7, "opacity", 1.0), ("opacity", True, "opacity", 1.0),
    ("color", "rojo", "color", None),
])
def test_un_dato_invalido_del_trazo_usa_el_de_fabrica(key, bad, field, expected):
    data = item_to_dict(S)
    data[key] = bad
    assert getattr(item_from_dict(data), field) == expected


@pytest.mark.parametrize("puntos", [None, [], "x", [[1, 2], [3]], [[1, "a"]], [[True, 2]], [1, 2], [[0, 0]] * 5001])
def test_un_trazo_con_puntos_invalidos_es_un_proyecto_danado(puntos):
    data = item_to_dict(S)
    data["points"] = puntos
    with pytest.raises(AnnotateError):
        item_from_dict(data)


def test_un_trazo_de_cientos_de_puntos_pesa_poco_en_el_proyecto():
    rng = random.Random(1)
    crudos = [(300 + 100 * math.cos(math.radians(i / 2)) + rng.uniform(-.8, .8), 300 + 100 * math.sin(math.radians(i / 2))) for i in range(721)]
    t = Stroke("g", freehand.process(crudos))
    assert len(str(item_to_dict(t))) < 1800        # ~700 puntos del mouse caben en unos 1.7 KB de proyecto
