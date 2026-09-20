import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core import brand as br
from core.annotate.io import load_doc, save_doc, sidecar_path
from core.annotate.palette import BRAND_PALETTE
from core.annotate.model import Marker, Rect
from core.geometry import CoverConfig
from core.user_settings import UserSettingsError
from ui.annotate.tab import AnnotateTab
from ui.brand_dialog import BrandDialog
from ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _brand():
    return br.Brand(name="Mi Marca", band="#112233", accent="#445566", text="#FFFFFF", outline="#000001",
                    subtitle_bg="#0A0B0C", subtitle_border="#0D0E0F", mark="#AA0000", glow="#BB0000",
                    lens="#CC0000", step="#DD0000", highlight="#EE0000")


@pytest.fixture
def tab(qapp, tmp_path):
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "cap.png")
    t = AnnotateTab()
    t.resize(1300, 800)
    t.show()
    QApplication.processEvents()
    return t


# --- dialogo ---------------------------------------------------------------------


def test_el_dialogo_muestra_la_marca_y_la_devuelve_editada(qapp):
    d = BrandDialog(_brand())
    assert d._name.text() == "Mi Marca" and set(d._pickers) == set(br.COLOR_KEYS)
    assert d._pickers["band"].hex_color() == "#112233"
    d._pickers["band"].set_hex_color("#abcdef")
    d._name.setText("  Otra  ")
    result = d.brand()
    assert result.band == "#ABCDEF" and result.name == "Otra"          # normalizada
    assert result.accent == "#445566"
    assert d.apply_now() is False


def test_restablecer_en_el_dialogo_vuelve_a_excel_solutions(qapp):
    d = BrandDialog(_brand())
    d._reset_btn.click()
    assert d.brand() == br.DEFAULT_BRAND


def test_aplicar_ahora_es_una_casilla_apagada_por_defecto(qapp):
    d = BrandDialog(br.DEFAULT_BRAND)
    assert not d._apply_now.isChecked()
    d._apply_now.setChecked(True)
    assert d.apply_now()


# --- Anotar -----------------------------------------------------------------------


def test_un_documento_nuevo_parte_de_la_paleta_de_la_marca(tab, tmp_path):
    br.save_brand(_brand())
    tab.load_capture(tmp_path / "cap.png")
    p = tab.doc.palette
    assert (p.marker, p.arrow, p.pen, p.glow, p.lens, p.step, p.highlight) == (
        "#AA0000", "#AA0000", "#AA0000", "#BB0000", "#CC0000", "#DD0000", "#EE0000")


def test_sin_marca_guardada_el_documento_nuevo_usa_los_colores_de_siempre(tab, tmp_path):
    tab.load_capture(tmp_path / "cap.png")
    assert tab.doc.palette == BRAND_PALETTE


def test_un_proyecto_guardado_conserva_su_paleta_aunque_cambie_la_marca(tab, tmp_path):
    tab.load_capture(tmp_path / "cap.png")
    tab.doc.items.append(Marker("a1", Rect(10, 10, 50, 30)))
    save_doc(tab.doc)
    br.save_brand(_brand())                                            # la marca cambia despues
    assert load_doc(sidecar_path(tmp_path / "cap.png")).palette == BRAND_PALETTE
    tab.load_capture(tmp_path / "cap.png")
    assert tab.doc.palette == BRAND_PALETTE                            # se abrio con la suya, no con la nueva marca


def test_restaurar_colores_de_marca_usa_la_marca_y_el_boton_depende_de_ella(tab, tmp_path):
    tab.load_capture(tmp_path / "cap.png")
    panel = tab.panel
    assert not panel._restore_btn.isEnabled()                          # ya esta en los colores de marca
    br.save_brand(_brand())
    panel.refresh_brand()
    assert panel._restore_btn.isEnabled()                              # la marca cambio: este documento ya no coincide
    panel._restore_btn.click()
    assert tab.doc.palette == br.brand_palette() and tab.doc.palette.marker == "#AA0000"
    assert not panel._restore_btn.isEnabled()
    tab.controller.undo()
    assert tab.doc.palette == BRAND_PALETTE                            # un solo paso de deshacer


def test_el_doble_clic_en_la_etiqueta_vuelve_al_color_de_la_marca(tab, tmp_path):
    br.save_brand(_brand())
    tab.load_capture(tmp_path / "cap.png")
    tab.panel._on_palette_color("marker", "#123456")
    assert tab.doc.palette.marker == "#123456"
    tab.panel._palette_pickers["marker"]                               # existe
    # lo que hace el doble clic en la etiqueta
    tab.panel._on_palette_color("marker", getattr(br.brand_palette(), "marker"))
    assert tab.doc.palette.marker == "#AA0000"


def test_el_boton_editar_colores_de_marca_emite_la_senal(tab, tmp_path):
    tab.load_capture(tmp_path / "cap.png")
    got = []
    tab.panel.editBrandRequested.connect(lambda: got.append(1))
    tab.panel._brand_btn.click()
    assert got == [1]


# --- ventana principal ------------------------------------------------------------


@pytest.fixture
def window(qapp):
    return MainWindow()


def test_sin_marca_la_ventana_arranca_con_lo_de_siempre(window):
    d = CoverConfig()
    for field in br.cover_overrides(br.DEFAULT_BRAND):                 # los colores (la fuente la ajusta la propia ventana)
        assert getattr(window.config, field) == getattr(d, field), field
    assert window.windowTitle() == "Cover Studio — Excel Solutions"


def test_la_ventana_arranca_con_la_marca_guardada(qapp):
    br.save_brand(_brand())
    w = MainWindow()
    assert w.config.band_color == "#112233" and w.band_color_picker.hex_color() == "#112233"
    assert w.config.subtitle_border_color2 == "#112233"
    assert w.windowTitle() == "Cover Studio — Mi Marca"


def test_restaurar_colores_de_marca_en_portada_incluye_el_subtitulo(qapp):
    br.save_brand(_brand())
    w = MainWindow()
    for picker in (w.band_color_picker, w.subtitle_bg_color_picker, w.subtitle_border_color2_picker,
                   w.subtitle_text_color_picker):
        picker.set_hex_color("#777777")
    w._on_restore_brand_colors_clicked()
    assert w.band_color_picker.hex_color() == "#112233"
    assert w.subtitle_bg_color_picker.hex_color() == "#0A0B0C"
    assert w.subtitle_border_color2_picker.hex_color() == "#112233"
    assert w.subtitle_text_color_picker.hex_color() == "#FFFFFF"
    assert w.config.band_color == "#112233" and w.config.subtitle_bg_color == "#0A0B0C"


def test_restablecer_todo_usa_los_colores_de_la_marca(qapp):
    br.save_brand(_brand())
    w = MainWindow()
    w.band_color_picker.set_hex_color("#777777")
    w._on_reset_all_clicked()
    assert w.config.band_color == "#112233"


def _accept_with(monkeypatch, apply_now, **colors):
    def fake_exec(self):
        for key, value in colors.items():
            self._pickers[key].set_hex_color(value)
        self._name.setText("Marca nueva")
        self._apply_now.setChecked(apply_now)
        return QDialog.Accepted

    monkeypatch.setattr(BrandDialog, "exec", fake_exec)


def test_editar_la_marca_guarda_sin_tocar_lo_abierto(qapp, monkeypatch, tmp_path):
    w = MainWindow()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "cap.png")
    w.annotate_tab.load_capture(tmp_path / "cap.png")
    _accept_with(monkeypatch, False, band="#102030", mark="#304050")
    w._on_edit_brand_clicked()
    saved = br.load_brand()
    assert saved.name == "Marca nueva" and saved.band == "#102030" and saved.mark == "#304050"
    assert w.windowTitle() == "Cover Studio — Marca nueva"
    assert w.config.band_color == CoverConfig().band_color             # el diseno abierto no cambio
    assert w.annotate_tab.doc.palette == BRAND_PALETTE                 # ni la captura abierta
    assert "Restaurar colores de marca" in w.statusBar().currentMessage()
    assert w.annotate_tab.panel._restore_btn.isEnabled()               # y ahora 'Restaurar' si sirve


def test_editar_la_marca_y_aplicar_ahora_actualiza_portada_y_anotar(qapp, monkeypatch, tmp_path):
    w = MainWindow()
    Image.new("RGB", (400, 300), (255, 255, 255)).save(tmp_path / "cap.png")
    w.annotate_tab.load_capture(tmp_path / "cap.png")
    _accept_with(monkeypatch, True, band="#102030", mark="#304050")
    w._on_edit_brand_clicked()
    assert w.config.band_color == "#102030" and w.band_color_picker.hex_color() == "#102030"
    assert w.annotate_tab.doc.palette.marker == "#304050"
    assert not w.annotate_tab.panel._restore_btn.isEnabled()


def test_cancelar_el_dialogo_no_guarda_nada(qapp, monkeypatch):
    monkeypatch.setattr(BrandDialog, "exec", lambda self: QDialog.Rejected)
    w = MainWindow()
    w._on_edit_brand_clicked()
    assert not br.brand_path().exists()


def test_si_no_se_puede_guardar_se_avisa_y_no_se_aplica_nada(qapp, monkeypatch):
    _accept_with(monkeypatch, True, band="#102030")
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[1]))
    monkeypatch.setattr("ui.main_window.save_brand", lambda b: (_ for _ in ()).throw(UserSettingsError("sin permiso")))
    w = MainWindow()
    w._on_edit_brand_clicked()
    assert shown and "colores de marca" in shown[0]
    assert w.config.band_color == CoverConfig().band_color and w.windowTitle() == "Cover Studio — Excel Solutions"


def test_el_boton_de_anotar_abre_el_mismo_dialogo_en_la_ventana(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(MainWindow, "_on_edit_brand_clicked", lambda self: calls.append(1))
    w = MainWindow()
    w.annotate_tab.panel.editBrandRequested.emit()
    assert calls == [1]
