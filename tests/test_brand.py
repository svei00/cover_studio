import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from core import brand as br
from core.annotate.palette import BRAND_PALETTE, palette_from_dict
from core.geometry import CoverConfig
from core.user_settings import UserSettingsError


def _custom(**kw):
    return br.Brand(name="Mi Marca", band="#112233", accent="#445566", text="#FFFFFF", outline="#000000",
                    subtitle_bg="#0A0B0C", subtitle_border="#0D0E0F", mark="#AA0000", glow="#BB0000",
                    lens="#CC0000", step="#DD0000", highlight="#EE0000", **kw)


# --- la marca por defecto es exactamente lo de siempre -----------------------------


def test_sin_archivo_la_marca_es_excel_solutions_y_nada_cambia():
    assert br.load_brand() == br.DEFAULT_BRAND and br.DEFAULT_BRAND.name == "Excel Solutions"
    assert br.default_cover_config() == CoverConfig()
    assert br.brand_palette() == BRAND_PALETTE


# --- guardar y cargar --------------------------------------------------------------


def test_guardar_y_cargar_la_marca():
    path = br.save_brand(_custom())
    assert path == br.brand_path() and path.name == "brand.json"
    assert br.load_brand() == _custom()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["name"] == "Mi Marca"
    assert data["colors"]["band"] == "#112233" and set(data["colors"]) == set(br.COLOR_KEYS)


def test_los_colores_se_normalizan_a_mayusculas_y_el_nombre_se_limpia():
    saved = br.Brand(name="  " + "x" * 200 + "  ", band="#abcdef", mark="no-es-un-color")
    br.save_brand(saved)
    loaded = br.load_brand()
    assert loaded.band == "#ABCDEF"
    assert loaded.mark == br.DEFAULT_BRAND.mark                  # invalido: el de siempre
    assert loaded.name == "x" * br.MAX_NAME_LENGTH


def test_un_nombre_vacio_vuelve_al_de_siempre():
    br.save_brand(br.Brand(name="   "))
    assert br.load_brand().name == br.DEFAULT_NAME


def test_cambiar_el_archivo_a_mano_se_nota_sin_reiniciar():
    br.save_brand(_custom())
    assert br.load_brand().band == "#112233"
    br.brand_path().write_text(json.dumps({"name": "Otra", "colors": {"band": "#998877"}}), encoding="utf-8")
    loaded = br.load_brand()
    assert loaded.name == "Otra" and loaded.band == "#998877"
    assert loaded.accent == br.DEFAULT_BRAND.accent               # lo que falta: el de siempre


@pytest.mark.parametrize("content", [
    "", "no es json", "[]", "null", '"texto"', '{"colors": 5}', '{"colors": {"band": 7, "accent": null}}',
    '{"name": 5, "colors": []}', "{",
])
def test_un_archivo_danado_nunca_falla_y_usa_la_marca_por_defecto(content):
    br.brand_path().parent.mkdir(parents=True, exist_ok=True)
    br.brand_path().write_text(content, encoding="utf-8")
    assert br.load_brand() == br.DEFAULT_BRAND


def test_los_colores_validos_se_conservan_aunque_otros_esten_danados():
    br.brand_path().parent.mkdir(parents=True, exist_ok=True)
    br.brand_path().write_text(
        json.dumps({"colors": {"band": "#123456", "accent": "rojo", "text": 3, "desconocido": "#000000"}}),
        encoding="utf-8",
    )
    loaded = br.load_brand()
    assert loaded.band == "#123456" and loaded.accent == br.DEFAULT_BRAND.accent and loaded.text == br.DEFAULT_BRAND.text


def test_no_poder_escribir_es_un_error_claro(tmp_path):
    blocker = tmp_path / "archivo"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(UserSettingsError, match="colores de marca"):
        br.save_brand(_custom(), blocker / "brand.json")        # la "carpeta" es un archivo


def test_no_queda_ningun_temporal_al_guardar():
    br.save_brand(_custom())
    assert [p.name for p in br.brand_path().parent.iterdir()] == ["brand.json"]


# --- como alimenta a las dos pestanas ----------------------------------------------


def test_la_marca_fija_los_colores_de_portada_incluidos_los_del_subtitulo():
    c = br.default_cover_config(_custom())
    assert (c.band_color, c.accent_color, c.text_color, c.text_outline_color) == ("#112233", "#445566", "#FFFFFF", "#000000")
    assert (c.subtitle_bg_color, c.subtitle_border_color) == ("#0A0B0C", "#0D0E0F")
    # los segundos colores de los degradados salen de la banda y del acento; el texto y el contorno del subtitulo de los suyos
    assert c.subtitle_border_color2 == "#112233" and c.subtitle_bg_color2 == "#445566"
    assert c.subtitle_text_color == "#FFFFFF" and c.subtitle_outline_color == "#000000"


def test_la_marca_no_toca_lo_que_no_es_color():
    c = br.default_cover_config(_custom())
    d = CoverConfig()
    assert (c.band_opacity, c.font_size, c.canvas, c.orientation, c.subtitle_gradient) == (
        d.band_opacity, d.font_size, d.canvas, d.orientation, d.subtitle_gradient)


def test_la_marca_fija_la_paleta_de_anotar():
    p = br.brand_palette(_custom())
    assert (p.marker, p.arrow, p.pen) == ("#AA0000", "#AA0000", "#AA0000")
    assert (p.glow, p.lens, p.step, p.highlight) == ("#BB0000", "#CC0000", "#DD0000", "#EE0000")


def test_las_funciones_usan_la_marca_guardada():
    br.save_brand(_custom())
    assert br.default_cover_config().band_color == "#112233"
    assert br.brand_palette().marker == "#AA0000"


def test_cada_color_de_la_marca_llega_a_algun_destino_y_solo_a_campos_que_existen():
    palette_fields = set(BRAND_PALETTE.__dataclass_fields__)
    cover_fields = set(CoverConfig.__dataclass_fields__)
    for key in br.COLOR_KEYS:
        targets = br._COVER_TARGETS.get(key) or br._PALETTE_TARGETS.get(key)
        assert targets, key
        assert set(targets) <= (cover_fields if key in br._COVER_TARGETS else palette_fields), key


def test_un_proyecto_viejo_sin_paleta_conserva_los_colores_de_siempre_aunque_haya_otra_marca():
    br.save_brand(_custom())
    assert palette_from_dict({}) == BRAND_PALETTE
    assert palette_from_dict({"marker": "no"}) == BRAND_PALETTE
