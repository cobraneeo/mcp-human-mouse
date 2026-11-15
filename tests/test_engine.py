"""Pruebas del motor con un backend falso (sin mover el ratón real)."""

from __future__ import annotations

import threading
import time

import pytest

from human_mouse.backends import Display
from human_mouse.engine import (
    HumanMouse,
    InvalidTarget,
    MotionBusy,
    PermissionDenied,
)
from human_mouse.trajectory import Bounds


class FakeBackend:
    name = "fake"
    platform = "test"

    def __init__(self, position: tuple[int, int] = (100, 100), trusted: bool = True) -> None:
        self._position = position
        self.trusted = trusted
        self.moves: list[tuple[int, int, str | None]] = []
        self.presses: list[tuple[str, int]] = []
        self.releases: list[tuple[str, int]] = []
        self.scrolls: list[tuple[int, int]] = []
        self.buttons: set[str] = set()

    def position(self) -> tuple[int, int]:
        return self._position

    def bounds(self) -> Bounds:
        return Bounds(0, 0, 1919, 1079)

    def displays(self) -> list[Display]:
        return [Display(id=1, x=0, y=0, width=1920, height=1080, main=True)]

    def move(self, x: int, y: int, *, dragged_button: str | None = None) -> None:
        self.moves.append((x, y, dragged_button))
        self._position = (x, y)

    def press(self, button: str, click_state: int = 1) -> None:
        self.presses.append((button, click_state))
        self.buttons.add(button)

    def release(self, button: str, click_state: int = 1) -> None:
        self.releases.append((button, click_state))
        self.buttons.discard(button)

    def scroll(self, dx: int, dy: int) -> None:
        self.scrolls.append((dx, dy))

    def buttons_down(self) -> set[str] | None:
        return set(self.buttons)

    def accessibility_trusted(self) -> bool | None:
        return self.trusted

    def permission_hint(self) -> str:
        return "permiso de prueba"

    def close(self) -> None:
        return None


def test_move_dry_run_no_toca_el_backend() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=True, seed=1)
    result = engine.move(500, 400)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["from"] == {"x": 100, "y": 100}
    assert result["to"] == {"x": 500, "y": 400}
    assert result["steps"] > 10
    assert backend.moves == []


def test_move_real_genera_eventos_y_termina_en_destino() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.move(400, 300, style="fast", duration_s=0.12)
    assert result["ok"] is True
    assert result["dry_run"] is False
    assert len(backend.moves) > 5
    assert backend.moves[-1][:2] == (400, 300)
    assert backend.position() == (400, 300)


def test_move_ajusta_al_borde_si_clamp() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=True, seed=1)
    result = engine.move(9999, -50, clamp=True)
    assert result["clamped"] is True
    assert result["to"] == {"x": 1919, "y": 0}


def test_move_fuera_de_pantalla_sin_clamp_falla() -> None:
    engine = HumanMouse(FakeBackend(), dry_run=True, seed=1)
    with pytest.raises(InvalidTarget):
        engine.move(9999, 0, clamp=False)


def test_permiso_denegado_impide_mover_pero_no_simular() -> None:
    backend = FakeBackend(trusted=False)
    engine = HumanMouse(backend, dry_run=False, seed=1)
    with pytest.raises(PermissionDenied):
        engine.move(200, 200)
    simulated = engine.move(200, 200, dry_run=True)
    assert simulated["dry_run"] is True
    assert backend.moves == []


def test_click_dry_run_no_pulsa() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=True, seed=1)
    result = engine.click(300, 300, clicks=2)
    assert result["ok"] is True
    assert result["clicks"] == 2
    assert backend.presses == []
    assert backend.releases == []
    assert result["approach"]["to"] == {"x": 300, "y": 300}


def test_doble_click_real_usa_click_state() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.click(300, 300, clicks=2, style="fast", duration_s=0.08)
    assert result["ok"] is True
    assert [c for _, c in backend.presses] == [1, 2]
    assert [c for _, c in backend.releases] == [1, 2]
    assert backend.buttons == set()


def test_click_sin_coordenadas_pulsa_en_la_posicion_actual() -> None:
    backend = FakeBackend(position=(777, 555))
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.click(style="fast")
    assert result["position"] == {"x": 777, "y": 555}
    assert backend.moves == []
    assert backend.presses == [("left", 1)]


def test_drag_pulsa_arrastra_y_suelta() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.drag(700, 500, style="fast", duration_s=0.12)
    assert result["ok"] is True
    assert backend.presses == [("left", 1)]
    assert backend.releases == [("left", 1)]
    assert all(button == "left" for _, _, button in backend.moves)
    assert backend.moves[-1][:2] == (700, 500)
    assert backend.buttons == set()


def test_drag_con_origen_se_acerca_antes() -> None:
    backend = FakeBackend(position=(0, 0))
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.drag(500, 500, from_x=200, from_y=200, style="fast", duration_s=0.08)
    assert result["approach"] is not None
    assert result["approach"]["to"] == {"x": 200, "y": 200}


def test_scroll_reparte_en_bloques_y_suma() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=False, seed=1)
    result = engine.scroll(-12)
    assert result["ok"] is True
    assert result["total"] == -12
    assert sum(dy for _, dy in backend.scrolls) == -12
    assert len(backend.scrolls) > 1


def test_scroll_cero_es_invalido() -> None:
    engine = HumanMouse(FakeBackend(), dry_run=True, seed=1)
    with pytest.raises(InvalidTarget):
        engine.scroll(0)


def test_busy_si_ya_hay_un_movimiento() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=True, seed=1)
    engine._lock.acquire()
    try:
        with pytest.raises(MotionBusy):
            engine.move(200, 200)
    finally:
        engine._lock.release()


def test_capture_registra_muestras_y_botones() -> None:
    backend = FakeBackend()
    engine = HumanMouse(backend, dry_run=False, seed=1)

    original_position = backend.position

    def moving_position() -> tuple[int, int]:
        t = time.perf_counter()
        return (100 + int(t * 100) % 200, 100)

    backend.position = moving_position  # type: ignore[method-assign]
    result = engine.capture(duration_s=0.25, sample_hz=40)
    backend.position = original_position  # type: ignore[method-assign]

    assert result["ok"] is True
    assert result["samples_count"] >= 5
    assert len(result["samples"]) == result["samples_count"]
    assert result["path_length_px"] >= 0
    assert all("t" in s and "x" in s and "y" in s for s in result["samples"])


def test_capture_sin_muestras() -> None:
    engine = HumanMouse(FakeBackend(), dry_run=False, seed=1)
    result = engine.capture(duration_s=0.2, sample_hz=20, include_samples=False)
    assert "samples" not in result
    assert result["samples_count"] >= 3


def test_state_y_diagnostics() -> None:
    backend = FakeBackend(position=(321, 123), trusted=True)
    engine = HumanMouse(backend, dry_run=False, seed=1)
    state = engine.state()
    assert state["position"] == {"x": 321, "y": 123}
    diag = engine.diagnostics()
    assert diag["backend"] == "fake"
    assert diag["accessibility"]["trusted"] is True
    assert diag["accessibility"]["can_move"] is True
    assert "natural" in diag["styles"]


def test_stop_interrumpe_un_movimiento_en_otro_hilo() -> None:
    engine = HumanMouse(FakeBackend(), dry_run=False, seed=1)
    errores: list[Exception] = []

    def trabajar() -> None:
        try:
            engine.move(1200, 900, style="fast", duration_s=1.0)
        except Exception as exc:  # noqa: BLE001 - se comprueba abajo
            errores.append(exc)

    hilo = threading.Thread(target=trabajar)
    hilo.start()
    time.sleep(0.20)
    resultado = engine.stop()
    hilo.join(timeout=3.0)

    assert not hilo.is_alive()
    assert resultado["was_moving"] is True
    assert errores
    assert getattr(errores[0], "code", "") == "aborted"


def test_stop_marca_la_senal() -> None:
    engine = HumanMouse(FakeBackend(), dry_run=True, seed=1)
    result = engine.stop()
    assert result["ok"] is True
    assert result["was_moving"] is False
    assert engine._stop.is_set()
