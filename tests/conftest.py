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
