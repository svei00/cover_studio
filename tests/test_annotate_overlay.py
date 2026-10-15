"""Imagen pegada encima de la captura (nucleo, sin Qt): composicion en el bitmap, geometria, edicion y proyecto."""

import io
import os

import pytest
from PIL import Image

from core.annotate import edit, overlay, raster, style
from core.annotate.errors import AnnotateError
from core.annotate.io import item_from_dict, item_to_dict
from core.annotate.model import AnnotationDoc, ImageOverlay, Magnifier, Marker, Rect, Redaction
from core.annotate.svg import render_bytes

RED = (220, 30, 30, 255)
WHITE = (255, 255, 255, 255)


@pytest.fixture
def pic(tmp_path):
    """Una imagen roja de 60 x 40."""
    path = tmp_path / "pegada.png"
    Image.new("RGBA", (60, 40), RED).save(path)
    return path


def _base(size=(200, 120), color=WHITE):
    return Image.new("RGBA", size, color)


def _ov(path, rect=Rect(20, 20, 60, 40), **kw):
    return ImageOverlay("p1", str(path), (60, 40), rect, **kw)


# --- composicion en el bitmap -------------------------------------------------------


def test_sin_imagenes_pegadas_devuelve_la_misma_imagen():
    img = _base()
    assert raster.apply_overlays(img, []) is img
    assert raster.apply_overlays(img, [Marker("m", Rect(1, 1, 5, 5))]) is img


def test_a_tamano_real_se_copia_pixel_por_pixel_y_no_toca_lo_demas(pic):
    out = raster.apply_overlays(_base(), [_ov(pic)])
    assert out.crop((20, 20, 80, 60)).tobytes() == Image.new("RGBA", (60, 40), RED).tobytes()
    assert out.getpixel((19, 20)) == WHITE and out.getpixel((80, 59)) == WHITE and out.getpixel((50, 60)) == WHITE


def test_no_modifica_la_imagen_original():
    img = _base()
    before = img.tobytes()
    raster.apply_overlays(img, [])
    assert img.tobytes() == before


def test_se_redimensiona_desde_el_original(pic):
    big = raster.apply_overlays(_base(), [_ov(pic, Rect(10, 10, 120, 80))])
    small = raster.apply_overlays(_base(), [_ov(pic, Rect(10, 10, 30, 20))])
    assert big.getpixel((60, 50)) == RED and small.getpixel((20, 15)) == RED
    assert big.getpixel((131, 91)) == WHITE and small.getpixel((41, 31)) == WHITE


def test_agrandar_reducir_y_volver_a_agrandar_da_lo_mismo_que_agrandar_directo(tmp_path):
    """Cada tamano sale del ORIGINAL: no se acumula degradacion (un degradado hace que cualquier remuestreo se note)."""
    path = tmp_path / "grad.png"
    grad = Image.new("RGBA", (64, 64))
    grad.putdata([(x * 4, y * 4, 128, 255) for y in range(64) for x in range(64)])
    grad.save(path)
    ov = lambda r: ImageOverlay("p1", str(path), (64, 64), r)
    direct = raster.apply_overlays(_base((300, 300)), [ov(Rect(0, 0, 200, 200))])
    raster.apply_overlays(_base((300, 300)), [ov(Rect(0, 0, 16, 16))])
    raster.apply_overlays(_base((300, 300)), [ov(Rect(0, 0, 100, 100))])
    again = raster.apply_overlays(_base((300, 300)), [ov(Rect(0, 0, 200, 200))])
    assert direct.tobytes() == again.tobytes()


def test_agrandar_suaviza_y_no_deja_bloques(tmp_path):
    path = tmp_path / "px.png"
    img = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    img.putpixel((1, 0), (255, 255, 255, 255))
    img.save(path)
    out = raster.apply_overlays(_base((100, 20)), [ImageOverlay("p", str(path), (2, 1), Rect(0, 0, 40, 10))])
    row = [out.getpixel((x, 5))[0] for x in range(40)]
    assert len(set(row)) > 4                                          # transicion gradual, no un escalon de bloques


def test_opacidad(pic):
    out = raster.apply_overlays(_base(), [_ov(pic, opacity=0.5)])
    r, g, b, _a = out.getpixel((50, 40))
    assert abs(r - 237) <= 2 and abs(g - 142) <= 2 and abs(b - 142) <= 2          # mitad rojo, mitad blanco


def test_esquinas_redondeadas_dejan_ver_el_fondo(pic):
    sq = raster.apply_overlays(_base(), [_ov(pic)])
    rd = raster.apply_overlays(_base(), [_ov(pic, corner=15)])
    assert sq.getpixel((21, 21)) == RED
    assert rd.getpixel((21, 21)) == WHITE and rd.getpixel((50, 40)) == RED


def test_la_transparencia_de_la_imagen_se_respeta(tmp_path):
    path = tmp_path / "t.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    img.paste(RED, (0, 0, 20, 40))
    img.save(path)
    out = raster.apply_overlays(_base(), [ImageOverlay("p", str(path), (40, 40), Rect(10, 10, 40, 40))])
    assert out.getpixel((15, 30)) == RED and out.getpixel((40, 30)) == WHITE


def test_la_ultima_queda_encima(pic, tmp_path):
    blue = tmp_path / "azul.png"
    Image.new("RGBA", (60, 40), (0, 0, 220, 255)).save(blue)
    a, b = _ov(pic), ImageOverlay("p2", str(blue), (60, 40), Rect(40, 30, 60, 40))
    assert raster.apply_overlays(_base(), [a, b]).getpixel((60, 45)) == (0, 0, 220, 255)
    assert raster.apply_overlays(_base(), [b, a]).getpixel((60, 45)) == RED


def test_lo_que_se_sale_de_la_captura_se_recorta(pic):
    partial = raster.apply_overlays(_base(), [_ov(pic, Rect(-20, -10, 60, 40))])
    assert partial.getpixel((5, 5)) == RED and partial.getpixel((45, 5)) == WHITE and partial.size == (200, 120)
    far = _base()
    assert raster.apply_overlays(far, [_ov(pic, Rect(900, 900, 60, 40))]).tobytes() == far.tobytes()


# --- sombra y borde -----------------------------------------------------------------


def test_la_sombra_cae_hacia_abajo_y_se_desvanece(pic):
    base = _base((200, 160))
    out = raster.apply_overlays(base, [_ov(pic, Rect(70, 50, 60, 40), shadow=True)], 1.0)
    below, above, far = out.getpixel((100, 94))[0], out.getpixel((100, 46))[0], out.getpixel((10, 150))[0]
    assert below < above < 255                      # mas oscura debajo que encima, y ambas con algo de sombra
    assert far == 255                               # lejos: intacto
    assert out.getpixel((100, 70)) == RED           # la imagen va por encima de su sombra


def test_la_intensidad_de_la_sombra_se_nota(pic):
    rect = Rect(70, 50, 60, 40)
    weak = raster.apply_overlays(_base((200, 160)), [_ov(pic, rect, shadow=True, shadow_strength=0.3)], 1.0)
    strong = raster.apply_overlays(_base((200, 160)), [_ov(pic, rect, shadow=True, shadow_strength=2.0)], 1.0)
    assert strong.getpixel((100, 94))[0] < weak.getpixel((100, 94))[0] < 255


def test_sin_sombra_no_hay_nada_fuera_de_la_imagen(pic):
    out = raster.apply_overlays(_base((200, 160)), [_ov(pic, Rect(70, 50, 60, 40))])
    assert out.getpixel((100, 94)) == WHITE


def test_la_sombra_escala_con_la_escala_del_documento(pic):
    """El alcance de la sombra (hasta que el fondo vuelve a ser blanco puro) crece con la escala del documento."""
    rect = Rect(200, 100, 60, 40)

    def reach(scale):
        out = raster.apply_overlays(_base((500, 400)), [_ov(pic, rect, shadow=True)], scale)
        return max(y for y in range(140, 400) if out.getpixel((230, y))[0] < 255) - 140

    small, normal, wide = reach(0.5), reach(1.0), reach(2.0)
    assert 0 < small < normal < wide


def test_la_sombra_pegada_al_borde_no_truena(pic):
    raster.apply_overlays(_base(), [_ov(pic, Rect(0, 0, 60, 40), shadow=True)])
    raster.apply_overlays(_base(), [_ov(pic, Rect(160, 90, 60, 40), shadow=True)])


def test_el_borde_fino_oscurece_el_contorno(tmp_path):
    path = tmp_path / "w.png"
    Image.new("RGBA", (60, 40), WHITE).save(path)
    ov = ImageOverlay("p", str(path), (60, 40), Rect(20, 20, 60, 40), border=True)
    out = raster.apply_overlays(_base(), [ov])
    assert out.getpixel((20, 40))[0] < 255 and out.getpixel((50, 40)) == WHITE


# --- archivos que faltan o cambian ---------------------------------------------------


def test_un_archivo_que_falta_se_omite_y_se_avisa(tmp_path):
    ghost = ImageOverlay("p", str(tmp_path / "no-existe.png"), (60, 40), Rect(0, 0, 60, 40))
    base = _base()
    assert raster.apply_overlays(base, [ghost]).tobytes() == base.tobytes()
    assert raster.missing_overlays([ghost, Marker("m", Rect(0, 0, 1, 1))]) == [ghost.path]


def test_un_archivo_danado_se_omite(tmp_path):
    bad = tmp_path / "mala.png"
    bad.write_bytes(b"esto no es una imagen")
    ov = ImageOverlay("p", str(bad), (60, 40), Rect(0, 0, 60, 40))
    assert raster.missing_overlays([ov]) == [str(bad)]


def test_si_el_archivo_cambia_se_vuelve_a_leer(pic):
    ov = _ov(pic)
    assert raster.apply_overlays(_base(), [ov]).getpixel((40, 40)) == RED
    Image.new("RGBA", (60, 40), (0, 200, 0, 255)).save(pic)
    os.utime(pic, ns=(10**18, 10**18 + 5))
    assert raster.apply_overlays(_base(), [ov]).getpixel((40, 40)) == (0, 200, 0, 255)


def test_orientacion_exif_se_respeta_como_en_la_captura(tmp_path):
    path = tmp_path / "exif.jpg"
    img = Image.new("RGB", (60, 40), (10, 10, 10))
    exif = img.getexif()
    exif[0x0112] = 6                                                    # girada 90 grados
    img.save(path, exif=exif)
    assert raster.load_image(path).size == (40, 60)


# --- el pipeline: pixelado, lupa y exportacion ---------------------------------------


def _doc(tmp_path, items):
    cap = tmp_path / "cap.png"
    Image.new("RGB", (200, 120), (255, 255, 255)).save(cap)
    return AnnotationDoc(image_path=cap, image_size=(200, 120), items=items)


def _png(doc):
    return Image.open(io.BytesIO(render_bytes(doc))).convert("RGB")


def test_exportar_incluye_la_imagen_pegada(tmp_path, pic):
    out = _png(_doc(tmp_path, [_ov(pic)]))
    assert out.getpixel((50, 40)) == RED[:3] and out.getpixel((150, 100)) == (255, 255, 255)


def test_pixelar_tambien_anonimiza_lo_pegado(tmp_path):
    stripes = tmp_path / "rayas.png"
    img = Image.new("RGBA", (60, 40), WHITE)
    for x in range(0, 60, 2):
        img.paste((0, 0, 0, 255), (x, 0, x + 1, 40))
    img.save(stripes)
    ov = ImageOverlay("p", str(stripes), (60, 40), Rect(20, 20, 60, 40))
    plain = _png(_doc(tmp_path, [ov]))
    pixelated = _png(_doc(tmp_path, [ov, Redaction("r", Rect(20, 20, 60, 40), 20)]))
    row = lambda im: [im.getpixel((x, 30))[0] for x in range(20, 40)]
    assert len(set(row(plain))) == 2 and len(set(row(pixelated))) <= 2 and row(plain) != row(pixelated)
    assert max(row(pixelated)) - min(row(pixelated)) < 255                       # ya no hay rayas negro/blanco puras


def test_la_lupa_puede_ampliar_lo_pegado(tmp_path, pic):
    lens = Magnifier("l", Rect(30, 30, 20, 20), (150.0, 40.0), 2.0)
    out = _png(_doc(tmp_path, [_ov(pic), lens]))
    assert out.getpixel((150, 40)) == RED[:3]                         # dentro del lente se ve lo pegado


def test_las_anotaciones_quedan_encima_de_lo_pegado(tmp_path, pic):
    marker = Marker("m", Rect(30, 30, 40, 20))
    with_overlay = _png(_doc(tmp_path, [_ov(pic), marker]))
    assert with_overlay.getpixel((30, 40)) != RED[:3]                 # el borde del marcador se ve sobre la imagen


# --- geometria ----------------------------------------------------------------------


def test_una_imagen_que_cabe_entra_a_tamano_real_y_centrada():
    r = overlay.initial_rect((300, 200), Rect(0, 0, 1000, 600))
    assert (r.w, r.h) == (300, 200) and (r.x, r.y) == (350, 200)
    assert all(float(v).is_integer() for v in (r.x, r.y, r.w, r.h))


def test_una_imagen_grande_se_reduce_conservando_la_proporcion():
    r = overlay.initial_rect((2000, 1000), Rect(0, 0, 800, 600))
    assert r.w <= 0.9 * 800 + 1 and r.h <= 0.9 * 600 + 1
    assert r.w / r.h == pytest.approx(2.0, abs=0.01) and r.center == pytest.approx((400, 300), abs=1)


def test_una_imagen_que_cabe_justo_o_casi_se_queda_al_100_por_ciento():
    exact = overlay.initial_rect((640, 360), Rect(0, 0, 640, 360))
    assert exact == Rect(0, 0, 640, 360)                                            # del tamano del lienzo: sin reducirla
    almost = overlay.initial_rect((790, 500), Rect(0, 0, 800, 500))
    assert (almost.w, almost.h) == (790, 500)
    over = overlay.initial_rect((801, 500), Rect(0, 0, 800, 500))
    assert over.w < 801 and over.w / over.h == pytest.approx(801 / 500, abs=0.01)     # no cabe: se reduce


def test_se_centra_en_la_parte_visible_si_hay_recorte():
    r = overlay.initial_rect((100, 50), Rect(300, 200, 400, 300))
    assert r.center == pytest.approx((500, 350), abs=1)


def test_tamano_real_y_porcentaje():
    item = ImageOverlay("p", "x.png", (100, 50), Rect(10, 10, 200, 100))
    assert overlay.scale_percent(item) == 200.0 and not overlay.is_real_size(item)
    real = overlay.real_size_rect(item)
    assert (real.w, real.h) == (100, 50) and real.center == item.rect.center
    assert overlay.is_real_size(ImageOverlay("p", "x.png", (100, 50), real))


# --- seleccion y edicion --------------------------------------------------------------


def _item(**kw):
    return ImageOverlay("p1", "x.png", (200, 100), kw.pop("rect", Rect(100, 100, 200, 100)), **kw)


def test_clic_dentro_selecciona_la_imagen_y_fuera_nada():
    assert edit.hit_test([_item()], (200, 150), 6, 1.0) == "p1"
    assert edit.hit_test([_item()], (20, 20), 6, 1.0) is None


def test_una_anotacion_encima_gana_a_la_imagen_aunque_se_creara_antes():
    marker = Marker("m", Rect(150, 120, 60, 40))
    assert edit.hit_test([marker, _item()], (150, 140), 6, 1.0) == "m"       # su borde, sobre la imagen
    assert edit.hit_test([marker, _item()], (180, 140), 6, 1.0) == "p1"      # dentro del marcador: lo que hay debajo


def test_tiene_las_ocho_asas_y_se_mueve():
    assert set(edit.item_handles(_item())) == set(edit.rect_handles(Rect(100, 100, 200, 100)))
    moved = edit.move_item(_item(), 10, -5)
    assert moved.rect == Rect(110, 95, 200, 100) and moved.size == (200, 100)
    assert edit.selection_rect(_item(), 1.0) == Rect(100, 100, 200, 100)


def test_una_esquina_conserva_la_proporcion_y_deja_fija_la_opuesta():
    se = edit.resize_item(_item(), edit.Handle.SE, (500, 250))
    assert se.rect.x == 100 and se.rect.y == 100 and se.rect.w / se.rect.h == pytest.approx(2.0)
    nw = edit.resize_item(_item(), edit.Handle.NW, (0, 0))
    assert nw.rect.right == pytest.approx(300) and nw.rect.bottom == pytest.approx(200)
    assert nw.rect.w / nw.rect.h == pytest.approx(2.0)


def test_los_lados_estiran_una_medida_y_la_otra_sigue_la_proporcion_desde_el_centro():
    e = edit.resize_item(_item(), edit.Handle.E, (500, 130))
    assert e.rect.x == 100 and e.rect.w == 400 and e.rect.h == pytest.approx(200) and e.rect.center[1] == pytest.approx(150)
    n = edit.resize_item(_item(), edit.Handle.N, (200, 0))
    assert n.rect.bottom == pytest.approx(200) and n.rect.h == pytest.approx(200) and n.rect.w == pytest.approx(400)


def test_con_mayus_se_estira_libre():
    free = edit.resize_item(_item(), edit.Handle.SE, (500, 130), free=True)
    assert free.rect == Rect(100, 100, 400, 30)


def test_no_baja_del_minimo_ni_se_invierte_al_cruzar_el_ancla():
    tiny = edit.resize_item(_item(), edit.Handle.SE, (50, 50))
    assert tiny.rect.w >= style.MIN_OVERLAY_SIZE and tiny.rect.h >= style.MIN_OVERLAY_SIZE - 1e-6
    assert tiny.rect.x == 100 and tiny.rect.y == 100
    assert tiny.rect.w / tiny.rect.h == pytest.approx(2.0)


def test_redimensionar_nunca_cambia_el_tamano_original():
    assert edit.resize_item(_item(), edit.Handle.SE, (700, 400)).size == (200, 100)


# --- proyecto -----------------------------------------------------------------------------


def test_se_guarda_y_se_recupera():
    item = _item(opacity=0.7, corner=8.0, shadow=True, shadow_strength=1.5, border=True)
    data = item_to_dict(item)
    assert data["type"] == "image" and data["size"] == [200, 100]
    assert item_from_dict(data) == item


def test_valores_malos_caen_a_los_de_fabrica():
    data = {"type": "image", "id": "a1", "path": "x.png", "size": [10, 10], "rect": [0, 0, 10, 10],
            "opacity": "mucha", "corner": 9999, "shadow": "si", "shadow_strength": -3, "border": 1}
    item = item_from_dict(data)
    assert (item.opacity, item.corner, item.shadow, item.shadow_strength, item.border) == (1.0, 0.0, False, 1.0, False)


@pytest.mark.parametrize("patch", [
    {"path": ""}, {"path": 5}, {"size": [0, 10]}, {"size": [10]}, {"size": "10x10"}, {"size": [10.5, 10]},
    {"size": [10, 10_000_000]}, {"size": [True, 10]},
])
def test_un_proyecto_sin_ruta_o_con_tamano_invalido_esta_danado(patch):
    data = {"type": "image", "id": "a1", "path": "x.png", "size": [10, 10], "rect": [0, 0, 10, 10], **patch}
    with pytest.raises(AnnotateError):
        item_from_dict(data)
