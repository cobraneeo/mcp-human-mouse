"""Selección del backend nativo adecuado."""

from __future__ import annotations

import sys

from .base import BackendUnavailable, Display, MouseBackend


def create_backend() -> MouseBackend:
    if sys.platform == "darwin":
        from .macos import MacOSBackend

        return MacOSBackend()
    if sys.platform.startswith("win"):
        from .windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux"):
        from .linux import LinuxBackend

        return LinuxBackend()
    raise BackendUnavailable(
        f"Plataforma no soportada: {sys.platform}",
        hint="Este servidor soporta macOS, Windows y Linux (X11).",
    )


__all__ = ["BackendUnavailable", "Display", "MouseBackend", "create_backend"]
