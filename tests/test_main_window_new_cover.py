"""Boton "Nueva portada": empezar otra sin cerrar la aplicacion (limpia el contenido, conserva el diseno)."""

import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.geometry import compute_band_geometry
from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    Image.new("RGB", (1600, 900), (40, 90, 140)).save(tmp_path / "foto.png")
    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    QApplication.processEvents()
    w._set_photo(tmp_path / "foto.png")
    w.title_edit.setPlainText("Titulo de la primera portada")
    w.subtitle_edit.setText("Un subtitulo")
    return w


def _confirma(window, monkeypatch, respuesta):
    llamadas = []
    monkeypatch.setattr(type(window), "_confirm_discard_cover", lambda self: llamadas.append(1) or respuesta)
    return llamadas


def _generar(window):
    window._on_generate_clicked()
    assert window.last_output_path is not None and window.last_output_path.exists()


def test_el_boton_existe_en_la_barra_de_arriba_con_su_atajo(window):
    assert window.new_cover_btn.text() == "Nueva portada"
    assert window.new_cover_btn.shortcut().toString() == "Ctrl+N"


def test_nueva_limpia_el_contenido_y_conserva_el_diseno(window, tmp_path, monkeypatch):
    _generar(window)
    window.band_color_picker.set_hex_color("#123456")
    window.config.band_color = "#123456"
    window.output_edit.setText(str(tmp_path / "a-mano.png"))
    window.output_edit.textEdited.emit("x")                           # la ruta se toco a mano
    assert window.output_manually_edited
    _generar(window)
    window.new_cover()
    assert window.title_edit.toPlainText() == "" and window.subtitle_edit.text() == ""
    assert window.photo_path is None and window.photo_edit.text() == "" and window.output_edit.text() == ""
    assert window.last_output_path is None and not window.open_folder_btn.isEnabled()
    assert not window.output_manually_edited
    assert window.config.band_color == "#123456"                      # el diseno sigue


def test_despues_de_nueva_la_ruta_de_salida_se_vuelve_a_rellenar_sola(window, tmp_path):
    window.output_edit.textEdited.emit("x")                           # antes de Nueva: ruta tocada a mano
    window.new_cover()
    Image.new("RGB", (800, 450), (10, 10, 10)).save(tmp_path / "otra.png")
    window._set_photo(tmp_path / "otra.png")
    window.title_edit.setPlainText("Otro titulo")
    assert window.output_edit.text() == str(tmp_path / "otro-titulo-cover.png")


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (80, 45), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _con_una_vista_previa_dibujada(window):
    """Deja en la vista previa lo que dejaria un render terminado (sin esperar al hilo)."""
    window.preview_widget._on_render_finished(_png_bytes(), compute_band_geometry(window.config), None)
    assert window.preview_widget._source_pixmap is not None and not window.preview_widget.pixmap().isNull()


def test_nueva_vacia_la_vista_previa_y_el_aviso_de_que_no_cabe(window):
    _con_una_vista_previa_dibujada(window)
    window.fit_warning_label.setVisible(True)
    window.new_cover()
    assert window.preview_widget._source_pixmap is None and window.preview_widget._band_rect is None
    assert window.preview_widget.pixmap().isNull() and "Genera una portada" in window.preview_widget.text()
    assert not window.fit_warning_label.isVisible()
    assert window.preview_widget._target_at(100.0, 100.0) is None      # ya no hay banda que arrastrar


def test_un_render_en_curso_al_pulsar_nueva_no_repone_la_portada_vieja(window):
    preview = window.preview_widget
    preview._render_in_flight = True                                   # un render sigue corriendo en su hilo
    preview._pending_request = {"config": window.config}               # y hay otro esperando
    window.new_cover()
    assert preview._pending_request is None                            # el pendiente se tira
    preview._on_render_finished(_png_bytes(), compute_band_geometry(window.config), None)   # el que corria termina
    assert preview._source_pixmap is None and preview.pixmap().isNull() and not preview._render_in_flight
    preview._render_in_flight = True
    preview._on_render_finished(_png_bytes(), compute_band_geometry(window.config), None)   # pero el siguiente si se dibuja
    assert preview._source_pixmap is not None


def test_si_el_render_en_curso_falla_despues_de_nueva_no_avisa_de_un_error_viejo(window):
    errores = []
    window.preview_widget.renderFailed.connect(errores.append)
    window.preview_widget._render_in_flight = True
    window.new_cover()
    window.preview_widget._on_render_failed("algo fallo")
    assert errores == [] and not window.preview_widget._render_in_flight


def test_escribir_despues_de_nueva_no_se_queda_con_la_foto_ni_el_texto_de_antes(window):
    window.new_cover()
    QTest.qWait(400)                                                  # el debounce ya vencio: no debe renderizar nada
    assert window.preview_widget._source_pixmap is None
    window.title_edit.setPlainText("Segunda portada")
    assert window.photo_path is None and window.subtitle_edit.text() == ""


# --- confirmacion ----------------------------------------------------------------------------------------

def test_con_cambios_sin_generar_pregunta_y_si_dice_que_no_no_pasa_nada(window, monkeypatch):
    llamadas = _confirma(window, monkeypatch, False)
    window._on_new_cover_clicked()
    assert llamadas == [1]
    assert window.title_edit.toPlainText() == "Titulo de la primera portada" and window.photo_path is not None


def test_con_cambios_sin_generar_y_confirmando_empieza_otra(window, monkeypatch):
    llamadas = _confirma(window, monkeypatch, True)
    window._on_new_cover_clicked()
    assert llamadas == [1] and window.title_edit.toPlainText() == ""


def test_si_ya_se_genero_y_no_hay_cambios_no_pregunta(window, monkeypatch):
    _generar(window)
    llamadas = _confirma(window, monkeypatch, False)
    window._on_new_cover_clicked()
    assert llamadas == [] and window.title_edit.toPlainText() == ""


def test_si_cambia_algo_despues_de_generar_vuelve_a_preguntar(window, monkeypatch):
    _generar(window)
    window.subtitle_edit.setText("Otro subtitulo")
    llamadas = _confirma(window, monkeypatch, False)
    window._on_new_cover_clicked()
    assert llamadas == [1] and window.subtitle_edit.text() == "Otro subtitulo"
    window.subtitle_edit.setText("Un subtitulo")                       # lo deja como estaba al generar
    window.config.band_opacity = 0.5                                  # y cambiar el diseno tambien cuenta
    window._on_new_cover_clicked()
    assert llamadas == [1, 1]


def test_sin_nada_escrito_no_pregunta_aunque_nunca_se_genero(qapp, monkeypatch):
    w = MainWindow()
    llamadas = _confirma(w, monkeypatch, False)
    w._on_new_cover_clicked()
    assert llamadas == []
