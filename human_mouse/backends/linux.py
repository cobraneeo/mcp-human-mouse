"""Backend Linux basado en pynput (X11 / XWayland)."""

from __future__ import annotations

from typing import Any

from ..trajectory import Bounds
from .base import BackendUnavailable, Display

_HINT = (
    "En Linux se necesita una sesión X11 o XWayland con DISPLAY accesible. "
    "En Wayland puro, pynput no puede publicar eventos globales."
)


class LinuxBackend:
    name = "linux-pynput"
    platform = "linux"

    def __init__(self) -> None:
        try:
            from pynput.mouse import Controller  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover
            raise BackendUnavailable(
                f"No se pudo importar pynput: {exc}",
                hint="Instala pynput y ejecuta el servidor en una sesión X11.",
            ) from exc
        try:
            self._mouse = Controller()
        except Exception as exc:  # pragma: no cover
            raise BackendUnavailable(f"No se pudo abrir el ratón: {exc}", hint=_HINT) from exc

        self._display: Any = None
        self._width = 1920
        self._height = 1080
        self._load_display()

    def _load_display(self) -> None:
        try:
            from Xlib import display  # type: ignore[import-not-found]

            self._display = display.Display()
            screen = self._display.screen()
            self._width = int(screen.width_in_pixels)
            self._height = int(screen.height_in_pixels)
        except Exception:
            self._display = None

    # -- lectura ---------------------------------------------------------
    def position(self) -> tuple[int, int]:
        x, y = self._mouse.position
        return int(round(x)), int(round(y))

    def displays(self) -> list[Display]:
        return [Display(id=0, x=0, y=0, width=self._width, height=self._height, main=True)]

    def bounds(self) -> Bounds:
        return Bounds(
            x_min=0.0,
            y_min=0.0,
            x_max=float(self._width - 1),
            y_max=float(self._height - 1),
        )

    def buttons_down(self) -> set[str] | None:
        return None

    def accessibility_trusted(self) -> bool | None:
        return None

    def permission_hint(self) -> str:
        return _HINT

    def request_access(self) -> bool | None:
        return self.accessibility_trusted()

    # -- escritura -------------------------------------------------------
    def move(self, x: int, y: int, *, dragged_button: str | None = None) -> None:
        self._mouse.position = (int(x), int(y))

    def _button(self, name: str) -> Any:
        from pynput.mouse import Button  # type: ignore[import-not-found]

        mapping = {
            "left": Button.left,
            "right": Button.right,
            "middle": Button.middle,
        }
        if name not in mapping:
            raise ValueError(f"Botón no soportado: {name}")
        return mapping[name]

    def press(self, button: str, click_state: int = 1) -> None:
        self._mouse.press(self._button(button))

    def release(self, button: str, click_state: int = 1) -> None:
        self._mouse.release(self._button(button))

    def scroll(self, dx: int, dy: int) -> None:
        self._mouse.scroll(int(dx), int(dy))

    def close(self) -> None:
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
