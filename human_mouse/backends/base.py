"""Contrato común de los backends de ratón."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..trajectory import Bounds


class BackendUnavailable(RuntimeError):
    """El backend no puede usarse en esta máquina."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Display:
    id: int
    x: int
    y: int
    width: int
    height: int
    main: bool = False

    @property
    def bounds(self) -> Bounds:
        return Bounds(
            x_min=float(self.x),
            y_min=float(self.y),
            x_max=float(self.x + self.width - 1),
            y_max=float(self.y + self.height - 1),
        )

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "main": self.main,
        }


class MouseBackend(Protocol):
    """Interfaz mínima que necesita el motor de movimiento."""

    name: str
    platform: str

    def position(self) -> tuple[int, int]:
        """Posición actual del cursor en puntos de pantalla."""

    def bounds(self) -> Bounds:
        """Rectángulo que engloba todos los monitores."""

    def displays(self) -> list[Display]:
        """Monitores activos."""

    def move(self, x: int, y: int, *, dragged_button: str | None = None) -> None:
        """Mueve el cursor generando un evento real de movimiento."""

    def press(self, button: str, click_state: int = 1) -> None: ...

    def release(self, button: str, click_state: int = 1) -> None: ...

    def scroll(self, dx: int, dy: int) -> None:
        """Desplazamiento en líneas; dy positivo = hacia arriba."""

    def buttons_down(self) -> set[str] | None:
        """Botones pulsados ahora mismo, o None si no se puede consultar."""

    def accessibility_trusted(self) -> bool | None:
        """True/False si el SO expone permisos; None si no aplica."""

    def permission_hint(self) -> str: ...

    def close(self) -> None: ...
