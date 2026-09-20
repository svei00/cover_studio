import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image, ImageDraw, ImageStat

from core.annotate import upscale as up
from core.annotate.errors import AnnotateError


def _text_like(size=(120, 60)):
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for x in range(10, size[0] - 10, 8):
        d.rectangle((x, 15, x + 2, 45), fill=(20, 20, 20, 255))
    return img


def _edge_contrast(img):
    """Contraste maximo entre vecinos horizontales en la fila central (mide la nitidez de los bordes)."""
    row = img.convert("L").crop((0, img.height // 2, img.width, img.height // 2 + 1))
    px = list(row.get_flattened_data()) if hasattr(row, "get_flattened_data") else list(row.getdata())
    return max(abs(a - b) for a, b in zip(px, px[1:]))


def test_tamano_y_nombre_de_salida(tmp_path):
    assert up.scaled_size((100, 50), 3) == (300, 150)
    assert up.scaled_output_path(tmp_path / "cap.jpg", 2) == tmp_path / "cap@2x.png"
    assert up.scaled_output_path(tmp_path / "cap.png", 4) == tmp_path / "cap@4x.png"


@pytest.mark.parametrize("factor", up.FACTORS)
def test_upscale_multiplica_las_dimensiones(factor):
    out = up.upscale(_text_like(), factor)
    assert out.size == (120 * factor, 60 * factor) and out.mode == "RGBA"


def test_factor_invalido_es_error():
    for bad in (0, 1, 5, -2):
        with pytest.raises(AnnotateError):
            up.upscale(_text_like(), bad)


def test_la_nitidez_deja_los_bordes_mas_marcados_que_solo_lanczos():
    img = _text_like()
    plain = up.upscale(img, 2, sharpen=False)
    sharp = up.upscale(img, 2, sharpen=True)
    assert _edge_contrast(sharp) > _edge_contrast(plain)
    # y no es un negativo ni se come la imagen: el brillo medio casi no cambia
    assert abs(ImageStat.Stat(sharp.convert("L")).mean[0] - ImageStat.Stat(plain.convert("L")).mean[0]) < 3


def test_la_nitidez_no_toca_el_alfa():
    img = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((10, 10, 29, 29), fill=(0, 0, 255, 255))
    plain = up.upscale(img, 2, sharpen=False)
    sharp = up.upscale(img, 2, sharpen=True)
    assert sharp.getchannel("A").tobytes() == plain.getchannel("A").tobytes()


def test_una_imagen_lisa_se_queda_lisa():
    img = Image.new("RGBA", (30, 30), (120, 130, 140, 255))
    out = up.upscale(img, 3)
    assert out.getextrema() == ((120, 120), (130, 130), (140, 140), (255, 255))


def test_demasiado_grande_se_rechaza_sin_reservar_memoria():
    class Huge:
        size = (9000, 9000)

    with pytest.raises(AnnotateError, match="demasiado grande"):
        up.upscale(Huge(), 4)   # 36000 x 36000: se comprueba ANTES de tocar la imagen


# --- guardar -------------------------------------------------------------------------


def test_save_upscaled_escribe_el_png_sin_tocar_el_original(tmp_path):
    src = tmp_path / "cap.png"
    _text_like((80, 40)).convert("RGB").save(src)
    before = src.read_bytes()
    out_path = up.scaled_output_path(src, 2)
    size = up.save_upscaled(src, out_path, 2)
    assert size == (160, 80)
    assert Image.open(out_path).size == (160, 80)
    assert Image.open(out_path).mode == "RGB"              # sin transparencia: se guarda sin alfa
    assert src.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_conserva_la_transparencia(tmp_path):
    src = tmp_path / "cap.png"
    img = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    img.putpixel((5, 5), (255, 0, 0, 255))
    img.save(src)
    out = up.scaled_output_path(src, 2)
    up.save_upscaled(src, out, 2)
    assert Image.open(out).mode == "RGBA"


def test_no_se_puede_sobrescribir_la_captura_original(tmp_path):
    src = tmp_path / "cap.png"
    _text_like().save(src)
    with pytest.raises(AnnotateError, match="original"):
        up.save_upscaled(src, src, 2)


def test_solo_guarda_png(tmp_path):
    src = tmp_path / "cap.png"
    _text_like().save(src)
    with pytest.raises(AnnotateError, match="PNG"):
        up.save_upscaled(src, tmp_path / "cap@2x.jpg", 2)


def test_captura_inexistente_es_error_claro(tmp_path):
    with pytest.raises(AnnotateError):
        up.save_upscaled(tmp_path / "no.png", tmp_path / "no@2x.png", 2)


# --- pestana -------------------------------------------------------------------------


def _tab(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.annotate.tab import AnnotateTab

    app = QApplication.instance() or QApplication([])
    Image.new("RGB", (200, 100), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    app.processEvents()
    return app, t


def test_el_boton_escalar_se_habilita_al_abrir_una_captura(tmp_path):
    app, t = _tab(tmp_path)
    assert not t.scale_btn.isEnabled()
    t.load_capture(tmp_path / "cap.png")
    app.processEvents()
    assert t.scale_btn.isEnabled()
    assert set(t.scale_actions) == set(up.FACTORS)


def test_escalar_desde_la_pestana_guarda_aparte_y_no_cambia_el_documento(tmp_path):
    app, t = _tab(tmp_path)
    t.load_capture(tmp_path / "cap.png")
    app.processEvents()
    doc_before = (t.doc.image_path, t.doc.image_size, list(t.doc.items))
    out = tmp_path / "cap@2x.png"
    assert t.scale_capture(2, out) is True
    assert Image.open(out).size == (400, 200)
    assert (t.doc.image_path, t.doc.image_size, list(t.doc.items)) == doc_before


def test_la_casilla_de_nitidez_se_respeta(tmp_path):
    app, t = _tab(tmp_path)
    img = _text_like((100, 50)).convert("RGB")
    img.save(tmp_path / "cap.png")
    t.load_capture(tmp_path / "cap.png")
    app.processEvents()
    t.sharpen_action.setChecked(False)
    t.scale_capture(2, tmp_path / "plain.png")
    t.sharpen_action.setChecked(True)
    t.scale_capture(2, tmp_path / "sharp.png")
    assert _edge_contrast(Image.open(tmp_path / "sharp.png")) > _edge_contrast(Image.open(tmp_path / "plain.png"))


def test_error_al_escalar_no_deja_archivo_ni_revienta(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    app, t = _tab(tmp_path)
    t.load_capture(tmp_path / "cap.png")
    app.processEvents()
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    assert t.scale_capture(2, t.doc.image_path) is False      # intentar pisar la original
    assert shown and "original" in shown[0]


def test_la_barra_superior_no_obliga_a_una_ventana_mas_ancha(tmp_path):
    """Con el boton Escalar la pestana llego a pedir 1408 px y rompia las pantallas de 1366: la etiqueta cede."""
    app, t = _tab(tmp_path)
    assert t.minimumSizeHint().width() <= 1300
