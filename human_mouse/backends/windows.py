"""Backend Windows basado en la API SendInput de user32."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..trajectory import Bounds
from .base import BackendUnavailable, Display

_MOVE = 0x0001
_LEFTDOWN = 0x0002
_LEFTUP = 0x0004
_RIGHTDOWN = 0x0008
_RIGHTUP = 0x0010
_MIDDLEDOWN = 0x0020
_MIDDLEUP = 0x0040
_WHEEL = 0x0800
_ABSOLUTE = 0x8000

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_INPUT_MOUSE = 0


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class WindowsBackend:
    name = "windows-sendinput"
    platform = "win32"

    def __init__(self) -> None:
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        except Exception as exc:  # pragma: no cover
            raise BackendUnavailable(f"No se pudo cargar user32: {exc}") from exc

        self._user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        )
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.GetCursorPos.argtypes = (ctypes.POINTER(_POINT),)
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = wintypes.SHORT

    # -- utilidades ------------------------------------------------------
    def _send(self, *inputs: _INPUT) -> None:
        array = (_INPUT * len(inputs))(*inputs)
        sent = self._user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            error = ctypes.get_last_error()
            raise RuntimeError(f"SendInput falló (código {error})")

    def _mouse_input(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
        event = _INPUT()
        event.type = _INPUT_MOUSE
        event.mi = _MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags)
        return event

    def _virtual_screen(self) -> tuple[int, int, int, int]:
        gsm = self._user32.GetSystemMetrics
        return (
            gsm(_SM_XVIRTUALSCREEN),
            gsm(_SM_YVIRTUALSCREEN),
            max(1, gsm(_SM_CXVIRTUALSCREEN)),
            max(1, gsm(_SM_CYVIRTUALSCREEN)),
        )

    def _absolute(self, x: int, y: int) -> tuple[int, int]:
        vx, vy, vw, vh = self._virtual_screen()
        nx = int(round((x - vx) * 65535 / max(1, vw - 1)))
        ny = int(round((y - vy) * 65535 / max(1, vh - 1)))
        return max(0, min(65535, nx)), max(0, min(65535, ny))

    # -- lectura ---------------------------------------------------------
    def position(self) -> tuple[int, int]:
        point = _POINT()
        if not self._user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("GetCursorPos falló")
        return int(point.x), int(point.y)

    def displays(self) -> list[Display]:
        vx, vy, vw, vh = self._virtual_screen()
        return [Display(id=0, x=vx, y=vy, width=vw, height=vh, main=True)]

    def bounds(self) -> Bounds:
        vx, vy, vw, vh = self._virtual_screen()
        return Bounds(
            x_min=float(vx),
            y_min=float(vy),
            x_max=float(vx + vw - 1),
            y_max=float(vy + vh - 1),
        )

    def buttons_down(self) -> set[str] | None:
        down: set[str] = set()
        for name, vk in (("left", 0x01), ("right", 0x02), ("middle", 0x04)):
            if self._user32.GetAsyncKeyState(vk) & 0x8000:
                down.add(name)
        return down

    def accessibility_trusted(self) -> bool | None:
        return None

    def request_access(self) -> bool | None:
        return self.accessibility_trusted()

    def permission_hint(self) -> str:
        return (
            "En Windows no hace falta un permiso especial. Si el ratón no se "
            "mueve, comprueba que el servidor corre en la misma sesión de "
            "usuario que el escritorio (no como servicio)."
        )

    # -- escritura -------------------------------------------------------
    def move(self, x: int, y: int, *, dragged_button: str | None = None) -> None:
        nx, ny = self._absolute(x, y)
        self._send(self._mouse_input(_MOVE | _ABSOLUTE, nx, ny))

    def press(self, button: str, click_state: int = 1) -> None:
        flags = {"left": _LEFTDOWN, "right": _RIGHTDOWN, "middle": _MIDDLEDOWN}
        self._send(self._mouse_input(flags[button]))

    def release(self, button: str, click_state: int = 1) -> None:
        flags = {"left": _LEFTUP, "right": _RIGHTUP, "middle": _MIDDLEUP}
        self._send(self._mouse_input(flags[button]))

    def scroll(self, dx: int, dy: int) -> None:
        if dy:
            self._send(self._mouse_input(_WHEEL, data=int(dy) * 120))
        if dx:
            self._send(self._mouse_input(_WHEEL | 0x01000, data=int(dx) * 120))

    def close(self) -> None:
        return None
