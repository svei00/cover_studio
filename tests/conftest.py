"""Configuracion compartida de las pruebas."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _sin_dialogos_modales(monkeypatch):
    """El dialogo de cambios sin guardar es modal: en una prueba sin nadie que lo
    conteste se queda esperando para siempre. Por defecto se descarta; las pruebas
    que verifican ese flujo lo sobreescriben."""
    try:
        from ui.annotate.tab import AnnotateTab
    except ImportError:  # PySide6 no instalado: las pruebas de UI se omiten solas
        return
    monkeypatch.setattr(AnnotateTab, "_ask_discard", lambda self: "discard")
    # lo mismo con el menu de clic derecho del lienzo: un QMenu.exec real es modal y cuelga la prueba
    from ui.annotate.canvas import AnnotateCanvas
    monkeypatch.setattr(AnnotateCanvas, "_exec_menu", lambda self, menu, global_pos: None)


@pytest.fixture(autouse=True)
def _datos_de_usuario_aislados(monkeypatch, tmp_path):
    """Las pruebas nunca deben leer ni escribir la carpeta de datos REAL del usuario (la carpeta Cover Studio dentro de APPDATA):
    cada prueba usa una carpeta temporal propia."""
    monkeypatch.setenv("COVER_STUDIO_HOME", str(tmp_path / "datos-de-usuario"))
