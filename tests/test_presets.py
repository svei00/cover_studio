from pathlib import Path

import pytest

from core.geometry import CoverConfig, Orientation
from core.presets import PresetError, config_from_dict, config_to_dict, list_presets, load_preset, save_preset


def test_config_to_dict_from_dict_roundtrip():
    config = CoverConfig(orientation=Orientation.TOP_LEFT, band_color="#000000")
    data = config_to_dict(config)
    assert config_from_dict(data) == config


def test_config_from_dict_usa_defaults_para_claves_faltantes():
    config = config_from_dict({"band_color": "#ABCDEF"})
    assert config.band_color == "#ABCDEF"
    assert config.accent_color == CoverConfig().accent_color


def test_save_and_load_preset_roundtrip(tmp_path: Path):
    config = CoverConfig(font_size=64, corner_radius=12)
    path = save_preset(config, "mi-preset", tmp_path)
    assert path.exists()
    loaded = load_preset(path)
    assert loaded == config


def test_save_preset_rechaza_nombre_vacio(tmp_path: Path):
    with pytest.raises(PresetError):
        save_preset(CoverConfig(), "   ", tmp_path)


def test_list_presets_ordena_por_nombre(tmp_path: Path):
    save_preset(CoverConfig(), "zeta", tmp_path)
    save_preset(CoverConfig(), "alfa", tmp_path)
    names = [p.stem for p in list_presets(tmp_path)]
    assert names == ["alfa", "zeta"]


def test_list_presets_directorio_inexistente(tmp_path: Path):
    assert list_presets(tmp_path / "no_existe") == []


def test_default_preset_incluido_carga_bien():
    default_path = Path(__file__).resolve().parent.parent / "presets" / "default.json"
    config = load_preset(default_path)
    assert config == CoverConfig()
