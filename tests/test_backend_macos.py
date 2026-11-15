"""Comprobaciones de integración con CoreGraphics (solo macOS)."""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")


def test_backend_macos_lee_estado_sin_permisos() -> None:
    from human_mouse.backends.macos import MacOSBackend

    backend = MacOSBackend()
    x, y = backend.position()
    bounds = backend.bounds()
    assert isinstance(x, int) and isinstance(y, int)
    assert bounds.width > 0 and bounds.height > 0
    assert bounds.contains(x, y)

    displays = backend.displays()
    assert displays
    assert any(d.main for d in displays)
    assert all(d.width > 0 and d.height > 0 for d in displays)

    trusted = backend.accessibility_trusted()
    assert trusted is None or isinstance(trusted, bool)
    assert isinstance(backend.buttons_down(), set)


def test_backend_macos_nombre() -> None:
    from human_mouse.backends.macos import MacOSBackend

    backend = MacOSBackend()
    assert backend.name == "macos-quartz"
    assert backend.platform == "darwin"
    assert "Accesibilidad" in backend.permission_hint()
