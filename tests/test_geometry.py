import pytest

from core.geometry import (
    BandGeometry,
    CoverConfig,
    GeometryError,
    Orientation,
    VerticalPosition,
    build_svg,
    compute_accent_path,
    compute_band_geometry,
    encode_image_data_uri,
    escape_xml,
)

BAND = BandGeometry(x=90, y=80, width=1590, height=210)


def test_escape_xml_escapa_caracteres_especiales():
    assert escape_xml('Tips & Trucos <Excel> "2026"') == (
        "Tips &amp; Trucos &lt;Excel&gt; &quot;2026&quot;"
    )


def test_compute_band_geometry_ancho_derivado():
    config = CoverConfig()
    band = compute_band_geometry(config)
    assert band.width == config.canvas.width - 2 * config.band_margin_left - 60
    assert band.x == config.band_margin_left
    assert band.y == config.band_margin_top


def test_compute_band_geometry_ancho_manual():
    config = CoverConfig(band_width=1200)
    band = compute_band_geometry(config)
    assert band.width == 1200


def test_compute_band_geometry_posicion_vertical_center():
    config = CoverConfig(vertical_position=VerticalPosition.CENTER)
    band = compute_band_geometry(config)
    assert band.y == (config.canvas.height - config.band_height) / 2


def test_compute_band_geometry_posicion_vertical_bottom():
    config = CoverConfig(vertical_position=VerticalPosition.BOTTOM)
    band = compute_band_geometry(config)
    assert band.y == config.canvas.height - config.band_margin_top - config.band_height


@pytest.mark.parametrize("orientation", list(Orientation))
def test_compute_accent_path_produce_geometria_valida(orientation):
    path = compute_accent_path(BAND, shift=30, corner_radius=0, orientation=orientation)
    assert path.startswith("M ")
    assert path.strip().endswith("Z")
    # 6 vertices del hexagono en L -> 6 comandos Q + 6 comandos L (uno por vertice) + M inicial
    assert path.count("Q ") == 6
    assert path.count("L ") == 6


@pytest.mark.parametrize("orientation", list(Orientation))
def test_compute_accent_path_con_esquinas_redondeadas_no_falla(orientation):
    path = compute_accent_path(BAND, shift=30, corner_radius=12, orientation=orientation)
    assert path.startswith("M ")
    assert path.strip().endswith("Z")


def test_compute_accent_path_arms_miden_el_shift_en_bottom_right():
    band = BandGeometry(x=0, y=0, width=800, height=200)
    shift = 30
    path = compute_accent_path(band, shift=shift, corner_radius=0, orientation=Orientation.BOTTOM_RIGHT)
    # con esquinas cuadradas: M(30,200) L(800,200) L(800,30) L(830,30) L(830,230) L(30,230) Z
    assert "M 30.00 200.00" in path
    assert "L 830.00 230.00" in path


def test_build_svg_incluye_titulo_escapado():
    config = CoverConfig()
    svg = build_svg(config, lines=["Excel & Contabilidad"], font_size=78)
    assert "Excel &amp; Contabilidad" in svg
    assert "<svg" in svg and "</svg>" in svg


def test_build_svg_sin_foto_usa_fondo_neutro():
    config = CoverConfig()
    svg = build_svg(config, lines=["Titulo"], font_size=78)
    assert 'fill="#6E6E6E"' in svg


def test_encode_image_data_uri_falla_si_no_existe(tmp_path):
    with pytest.raises(GeometryError):
        encode_image_data_uri(tmp_path / "no_existe.png")


def test_encode_image_data_uri_falla_con_formato_no_soportado(tmp_path):
    bogus = tmp_path / "foto.gif"
    bogus.write_bytes(b"not a real gif")
    with pytest.raises(GeometryError):
        encode_image_data_uri(bogus)


def test_encode_image_data_uri_ok_con_png_valido(tmp_path):
    from PIL import Image

    photo = tmp_path / "foto.png"
    Image.new("RGB", (10, 10), color="red").save(photo)
    data_uri = encode_image_data_uri(photo)
    assert data_uri.startswith("data:image/png;base64,")
