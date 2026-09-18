import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from core import user_settings
from core.user_settings import (
    MAX_CUSTOM_COLORS,
    UserSettingsError,
    custom_colors_path,
    load_custom_colors,
    save_custom_colors,
    user_data_dir,
)

VACIO = [None] * MAX_CUSTOM_COLORS


# --- carpeta de datos ------------------------------------------------------------------------

def test_la_carpeta_de_datos_se_puede_cambiar_con_una_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("COVER_STUDIO_HOME", str(tmp_path / "otra"))
    assert user_data_dir() == tmp_path / "otra"
    assert custom_colors_path() == tmp_path / "otra" / "custom_colors.json"


def test_por_defecto_va_a_la_carpeta_del_usuario_y_no_al_proyecto(monkeypatch):
    monkeypatch.delenv("COVER_STUDIO_HOME")
    carpeta = user_data_dir()
    proyecto = Path(__file__).resolve().parent.parent
    assert proyecto not in carpeta.parents and carpeta != proyecto
    assert carpeta.name in ("Cover Studio", "cover-studio")


def test_las_pruebas_estan_aisladas_del_appdata_real():
    # el fixture automatico de conftest apunta a una carpeta temporal
    assert "datos-de-usuario" in str(user_data_dir())


# --- guardar y cargar ----------------------------------------------------------------------------

def test_sin_archivo_no_hay_colores_y_no_falla():
    assert load_custom_colors() == VACIO


def test_se_guardan_y_se_recuperan_en_su_posicion(tmp_path):
    colores = ["#336699", None, "#ABCDEF", None, "#000000"]
    ruta = save_custom_colors(colores, tmp_path / "c.json")
    cargados = load_custom_colors(ruta)
    assert cargados[:5] == ["#336699", None, "#abcdef", None, "#000000"]   # en minusculas y en el mismo espacio
    assert len(cargados) == MAX_CUSTOM_COLORS and cargados[5:] == [None] * 11


def test_el_archivo_es_un_json_legible_con_version(tmp_path):
    ruta = save_custom_colors(["#112233"], tmp_path / "c.json")
    data = json.loads(ruta.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["custom_colors"][0] == "#112233" and len(data["custom_colors"]) == MAX_CUSTOM_COLORS


def test_se_crea_la_carpeta_y_no_quedan_temporales(tmp_path):
    ruta = save_custom_colors(["#112233"], tmp_path / "no" / "existe" / "c.json")
    assert ruta.exists() and [p.name for p in ruta.parent.iterdir()] == ["c.json"]


def test_guardar_de_nuevo_reemplaza(tmp_path):
    ruta = tmp_path / "c.json"
    save_custom_colors(["#111111", "#222222"], ruta)
    save_custom_colors(["#333333"], ruta)
    assert load_custom_colors(ruta)[:2] == ["#333333", None]


def test_mas_de_dieciseis_se_recortan_y_los_invalidos_quedan_vacios(tmp_path):
    ruta = save_custom_colors(["#111111"] * 20, tmp_path / "c.json")
    assert load_custom_colors(ruta) == ["#111111"] * MAX_CUSTOM_COLORS
    ruta = save_custom_colors(["rojo", "#12", 5, None, "#ABCDEF"], tmp_path / "d.json")
    assert load_custom_colors(ruta)[:5] == [None, None, None, None, "#abcdef"]


@pytest.mark.parametrize("contenido", [
    "esto no es json", "", "[]", "42", "null", '{"custom_colors": "no soy lista"}', '{"otra": 1}',
    '{"custom_colors": [1, 2, 3]}', '{"custom_colors": [["#112233"]]}',
])
def test_un_archivo_danado_no_impide_abrir_la_app(tmp_path, contenido):
    ruta = tmp_path / "c.json"
    ruta.write_text(contenido, encoding="utf-8")
    assert load_custom_colors(ruta) == VACIO


def test_un_archivo_a_medias_conserva_lo_valido(tmp_path):
    ruta = tmp_path / "c.json"
    ruta.write_text(json.dumps({"custom_colors": ["#112233", "mal", "#445566"]}), encoding="utf-8")
    assert load_custom_colors(ruta)[:3] == ["#112233", None, "#445566"]


def test_si_no_se_puede_escribir_avisa_con_un_error_claro(tmp_path):
    bloqueo = tmp_path / "es-un-archivo"
    bloqueo.write_text("x", encoding="utf-8")
    with pytest.raises(UserSettingsError, match="colores personalizados"):
        save_custom_colors(["#112233"], bloqueo / "c.json")   # la "carpeta" es un archivo


def test_una_escritura_fallida_no_deja_el_archivo_anterior_roto(tmp_path, monkeypatch):
    ruta = tmp_path / "c.json"
    save_custom_colors(["#111111"], ruta)

    def falla(*_a, **_k):
        raise OSError("disco lleno")

    monkeypatch.setattr(user_settings.os, "replace", falla)
    with pytest.raises(UserSettingsError):
        save_custom_colors(["#999999"], ruta)
    assert load_custom_colors(ruta)[0] == "#111111"                      # el archivo bueno sigue intacto
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]            # y no queda un temporal


# --- el selector de color de la interfaz ---------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from ui import widgets
from ui.widgets import ColorPickerButton, persist_custom_colors, restore_custom_colors


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def limpiar_qt(qapp):
    """Cada prueba arranca como una sesion nueva: espacios en blanco en Qt y estado del modulo olvidado."""
    def blanquear():
        for i in range(QColorDialog.customCount()):
            QColorDialog.setCustomColor(i, QColor("#ffffff"))
        widgets._reset_custom_colors_state()

    blanquear()
    yield
    blanquear()


def _qt_colores():
    return [QColorDialog.customColor(i).name() for i in range(MAX_CUSTOM_COLORS)]


def test_los_colores_guardados_aparecen_en_el_selector_al_abrir_otra_sesion():
    save_custom_colors(["#336699", None, "#abcdef"])
    assert _qt_colores()[:3] == ["#ffffff", "#ffffff", "#ffffff"]      # una sesion nueva empieza en blanco...
    restore_custom_colors()
    assert _qt_colores()[:3] == ["#336699", "#ffffff", "#abcdef"]      # ...y aqui vuelven


def test_restaurar_ocurre_una_sola_vez_por_sesion():
    save_custom_colors(["#336699"])
    restore_custom_colors()
    QColorDialog.setCustomColor(0, QColor("#111111"))                    # el usuario cambia uno
    restore_custom_colors()
    assert QColorDialog.customColor(0).name() == "#111111"              # no se pisa con lo del disco


def test_una_sesion_completa_ida_y_vuelta():
    restore_custom_colors()
    QColorDialog.setCustomColor(0, QColor("#ab12cd"))                    # "Agregar a personalizados"
    QColorDialog.setCustomColor(5, QColor("#00ff7f"))
    assert persist_custom_colors() is True
    # se cierra la app y se abre otra vez
    for i in range(MAX_CUSTOM_COLORS):
        QColorDialog.setCustomColor(i, QColor("#ffffff"))
    widgets._reset_custom_colors_state()
    restore_custom_colors()
    assert QColorDialog.customColor(0).name() == "#ab12cd" and QColorDialog.customColor(5).name() == "#00ff7f"


def test_no_se_reescribe_el_archivo_si_nada_cambio(monkeypatch):
    llamadas = []
    original = widgets.save_custom_colors
    monkeypatch.setattr(widgets, "save_custom_colors", lambda c: (llamadas.append(1), original(c))[1])
    restore_custom_colors()
    assert persist_custom_colors() is True and llamadas == []            # nada cambio: no escribe
    QColorDialog.setCustomColor(2, QColor("#123456"))
    persist_custom_colors()
    persist_custom_colors()
    assert llamadas == [1]                                               # cambio una vez: escribe una vez


def test_un_fallo_al_guardar_no_tumba_la_app(monkeypatch, capsys):
    restore_custom_colors()
    QColorDialog.setCustomColor(1, QColor("#123456"))

    def falla(_colores):
        raise UserSettingsError("sin permisos")

    monkeypatch.setattr(widgets, "save_custom_colors", falla)
    assert persist_custom_colors() is False
    assert "sin permisos" in capsys.readouterr().err


def test_al_pulsar_el_color_se_restauran_y_se_guardan_los_personalizados(monkeypatch):
    save_custom_colors(["#336699"])
    visto = {}

    def dialogo_falso(inicial, parent, titulo):
        visto["al_abrir"] = QColorDialog.customColor(0).name()            # ya estaban restaurados
        QColorDialog.setCustomColor(3, QColor("#ab12cd"))                 # el usuario agrega uno nuevo
        return QColor("#445566")

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(dialogo_falso))
    boton = ColorPickerButton("#000000")
    cambios = []
    boton.colorChanged.connect(cambios.append)
    boton._on_swatch_clicked(None)
    assert visto["al_abrir"] == "#336699" and cambios == ["#445566"]
    guardados = load_custom_colors()
    assert guardados[0] == "#336699" and guardados[3] == "#ab12cd"


def test_tambien_se_guarda_si_se_cancela_el_dialogo(monkeypatch):
    def dialogo_cancelado(inicial, parent, titulo):
        QColorDialog.setCustomColor(7, QColor("#fedcba"))                 # lo agrego y luego cancelo
        return QColor()                                                    # color invalido = cancelado

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(dialogo_cancelado))
    boton = ColorPickerButton("#000000")
    cambios = []
    boton.colorChanged.connect(cambios.append)
    boton._on_swatch_clicked(None)
    assert cambios == [] and boton.hex_color() == "#000000"               # el color del boton no cambio
    assert load_custom_colors()[7] == "#fedcba"                           # pero el personalizado si se guardo


def test_el_selector_abre_el_dialogo_de_qt_con_16_espacios():
    assert QColorDialog.customCount() == MAX_CUSTOM_COLORS
