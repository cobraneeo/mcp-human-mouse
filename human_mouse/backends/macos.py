"""Backend macOS basado en CoreGraphics (Quartz).

Publica eventos reales de ratón en el HID event tap, no simples warps del
cursor. Requiere permiso de Accesibilidad para el proceso responsable (la app
que lanza el servidor MCP).
"""

from __future__ import annotations

import ctypes
from typing import Any

from ..trajectory import Bounds
from .base import BackendUnavailable, Display

try:  # pragma: no cover - depende de macOS
    import Quartz  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover
    Quartz = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


_HINT = (
    "Concede permiso de Accesibilidad a la aplicación que lanza este servidor "
    "(DeepSeek Harness / IDE .NET o Terminal): Ajustes del Sistema → "
    "Privacidad y seguridad → Accesibilidad. Después reinicia el servidor MCP."
)

_BUTTONS: dict[str, tuple[int, int, int, int, int]] = {}
if Quartz is not None:  # pragma: no branch
    _BUTTONS = {
        "left": (
            int(Quartz.kCGMouseButtonLeft),
            int(Quartz.kCGEventLeftMouseDown),
            int(Quartz.kCGEventLeftMouseUp),
            int(Quartz.kCGEventLeftMouseDragged),
            int(Quartz.kCGEventMouseMoved),
        ),
        "right": (
            int(Quartz.kCGMouseButtonRight),
            int(Quartz.kCGEventRightMouseDown),
            int(Quartz.kCGEventRightMouseUp),
            int(Quartz.kCGEventRightMouseDragged),
            int(Quartz.kCGEventMouseMoved),
        ),
        "middle": (
            int(Quartz.kCGMouseButtonCenter),
            int(Quartz.kCGEventOtherMouseDown),
            int(Quartz.kCGEventOtherMouseUp),
            int(Quartz.kCGEventOtherMouseDragged),
            int(Quartz.kCGEventMouseMoved),
        ),
    }


class MacOSBackend:
    name = "macos-quartz"
    platform = "darwin"

    def __init__(self) -> None:
        if Quartz is None:
            raise BackendUnavailable(
                f"No se pudo importar Quartz: {_IMPORT_ERROR}",
                hint="Instala pyobjc-framework-Quartz en el entorno del servidor.",
            )
        self._last: tuple[int, int] | None = None
        self._cg = self._load_cg()

    @staticmethod
    def _load_cg() -> Any:
        try:
            cg = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
            )
            cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
            cg.CGPreflightPostEventAccess.argtypes = []
            cg.CGRequestPostEventAccess.restype = ctypes.c_bool
            cg.CGRequestPostEventAccess.argtypes = []
            return cg
        except Exception:
            return None

    # -- lectura ---------------------------------------------------------
    def position(self) -> tuple[int, int]:
        event = Quartz.CGEventCreate(None)
        location = Quartz.CGEventGetLocation(event)
        return int(round(location.x)), int(round(location.y))

    def displays(self) -> list[Display]:
        try:
            _, ids, _ = Quartz.CGGetActiveDisplayList(32, None, None)
            display_ids = [int(i) for i in ids]
        except Exception:
            display_ids = [int(Quartz.CGMainDisplayID())]

        main_id = int(Quartz.CGMainDisplayID())
        result: list[Display] = []
        for display_id in display_ids:
            rect = Quartz.CGDisplayBounds(display_id)
            result.append(
                Display(
                    id=display_id,
                    x=int(round(rect.origin.x)),
                    y=int(round(rect.origin.y)),
                    width=int(round(rect.size.width)),
                    height=int(round(rect.size.height)),
                    main=display_id == main_id,
                )
            )
        if not result:
            rect = Quartz.CGDisplayBounds(main_id)
            result.append(
                Display(
                    id=main_id,
                    x=int(round(rect.origin.x)),
                    y=int(round(rect.origin.y)),
                    width=int(round(rect.size.width)),
                    height=int(round(rect.size.height)),
                    main=True,
                )
            )
        return result

    def bounds(self) -> Bounds:
        displays = self.displays()
        return Bounds(
            x_min=float(min(d.x for d in displays)),
            y_min=float(min(d.y for d in displays)),
            x_max=float(max(d.x + d.width - 1 for d in displays)),
            y_max=float(max(d.y + d.height - 1 for d in displays)),
        )

    def buttons_down(self) -> set[str] | None:
        state = int(Quartz.kCGEventSourceStateCombinedSessionState)
        down: set[str] = set()
        for name, (button, *_rest) in _BUTTONS.items():
            try:
                if Quartz.CGEventSourceButtonState(state, button):
                    down.add(name)
            except Exception:
                return None
        return down

    def accessibility_trusted(self) -> bool | None:
        if self._cg is not None:
            try:
                return bool(self._cg.CGPreflightPostEventAccess())
            except Exception:
                pass
        try:
            trusted = Quartz.AXIsProcessTrusted
        except AttributeError:
            return None
        try:
            return bool(trusted())
        except Exception:
            return None

    def permission_hint(self) -> str:
        return _HINT

    def request_access(self) -> bool | None:
        """Pide permiso al sistema (en macOS muestra el diálogo de TCC)."""
        if self._cg is not None:
            try:
                return bool(self._cg.CGRequestPostEventAccess())
            except Exception:
                pass
        return self.accessibility_trusted()

    # -- escritura -------------------------------------------------------
    def move(self, x: int, y: int, *, dragged_button: str | None = None) -> None:
        if dragged_button is not None:
            _, _, _, dragged_event, _ = _BUTTONS[dragged_button]
            event_type = dragged_event
            button = _BUTTONS[dragged_button][0]
        else:
            event_type = int(Quartz.kCGEventMouseMoved)
            button = int(Quartz.kCGMouseButtonLeft)

        event = Quartz.CGEventCreateMouseEvent(
            None, event_type, (float(x), float(y)), button
        )
        if self._last is not None:
            dx = int(round(x - self._last[0]))
            dy = int(round(y - self._last[1]))
            if dx or dy:
                Quartz.CGEventSetIntegerValueField(
                    event, int(Quartz.kCGMouseEventDeltaX), dx
                )
                Quartz.CGEventSetIntegerValueField(
                    event, int(Quartz.kCGMouseEventDeltaY), dy
                )
        Quartz.CGEventPost(int(Quartz.kCGHIDEventTap), event)
        self._last = (x, y)

    def _button_event(self, button_name: str, down: bool, click_state: int) -> None:
        try:
            meta = _BUTTONS[button_name]
        except KeyError as exc:
            raise ValueError(f"Botón no soportado: {button_name}") from exc

        button, down_type, up_type, _, _ = meta
        x, y = self.position()
        event = Quartz.CGEventCreateMouseEvent(
            None, down_type if down else up_type, (float(x), float(y)), button
        )
        Quartz.CGEventSetIntegerValueField(
            event, int(Quartz.kCGMouseEventClickState), int(click_state)
        )
        Quartz.CGEventPost(int(Quartz.kCGHIDEventTap), event)
        self._last = (x, y)

    def press(self, button: str, click_state: int = 1) -> None:
        self._button_event(button, True, click_state)

    def release(self, button: str, click_state: int = 1) -> None:
        self._button_event(button, False, click_state)

    def scroll(self, dx: int, dy: int) -> None:
        event = Quartz.CGEventCreateScrollWheelEvent(
            None,
            int(Quartz.kCGScrollEventUnitLine),
            2,
            int(dy),
            int(dx),
        )
        Quartz.CGEventPost(int(Quartz.kCGHIDEventTap), event)

    def close(self) -> None:
        return None
