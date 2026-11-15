"""Motor de movimiento: convierte trayectorias en eventos reales de ratón."""

from __future__ import annotations

import math
import os
import random
import threading
import time
from contextlib import contextmanager
from .backends import BackendUnavailable, MouseBackend, create_backend
from .trajectory import (
    STYLES,
    GeneratedPath,
    Style,
    available_styles,
    build_path,
)

MAX_DURATION_S = 30.0
MAX_STEPS_PER_MOVE = 6000


class HumanMouseError(RuntimeError):
    """Error controlado que el servidor MCP devuelve como resultado."""

    code = "error"
    hint: str | None = None

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class MotionBusy(HumanMouseError):
    code = "busy"


class MotionAborted(HumanMouseError):
    code = "aborted"


class InvalidTarget(HumanMouseError):
    code = "invalid_target"


class PermissionDenied(HumanMouseError):
    code = "permission_denied"


class BackendError(HumanMouseError):
    code = "backend_unavailable"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


class HumanMouse:
    """Fachada de alto nivel sobre un backend de ratón."""

    def __init__(
        self,
        backend: MouseBackend | None = None,
        *,
        dry_run: bool | None = None,
        seed: int | None = None,
        speed_scale: float | None = None,
        max_duration_s: float | None = None,
        allow_untrusted: bool | None = None,
    ) -> None:
        self._backend = backend
        self.dry_run = _env_bool("HUMAN_MOUSE_DRY_RUN") if dry_run is None else dry_run
        env_seed = os.environ.get("HUMAN_MOUSE_SEED")
        self.seed = seed if seed is not None else (int(env_seed) if env_seed else None)
        self.speed_scale = max(
            0.05,
            speed_scale if speed_scale is not None else _env_float("HUMAN_MOUSE_SPEED", 1.0),
        )
        self.max_duration_s = min(
            120.0,
            max(
                0.5,
                max_duration_s
                if max_duration_s is not None
                else _env_float("HUMAN_MOUSE_MAX_DURATION", MAX_DURATION_S),
            ),
        )
        self.allow_untrusted = (
            _env_bool("HUMAN_MOUSE_ALLOW_UNTRUSTED")
            if allow_untrusted is None
            else allow_untrusted
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rng = random.Random(self.seed)

    # -- infraestructura -------------------------------------------------
    @property
    def backend(self) -> MouseBackend:
        if self._backend is None:
            try:
                self._backend = create_backend()
            except BackendUnavailable as exc:
                raise BackendError(str(exc), exc.hint) from exc
        return self._backend

    @contextmanager
    def _motion(self):
        if not self._lock.acquire(blocking=False):
            raise MotionBusy(
                "Ya hay un movimiento en curso. Espera a que termine o llama a stop.",
            )
        try:
            self._stop.clear()
            yield
        finally:
            self._lock.release()

    def _style(self, name: str) -> Style:
        try:
            return STYLES[name]
        except KeyError as exc:
            raise InvalidTarget(
                f"Estilo desconocido: {name!r}",
                hint=f"Estilos válidos: {', '.join(STYLES)}",
            ) from exc

    def _resolve_target(
        self, x: float, y: float, clamp: bool
    ) -> tuple[tuple[int, int], bool]:
        if not (math.isfinite(float(x)) and math.isfinite(float(y))):
            raise InvalidTarget("Las coordenadas deben ser números finitos.")
        bounds = self.backend.bounds()
        requested = (int(round(float(x))), int(round(float(y))))
        if bounds.contains(*requested):
            return requested, False
        if not clamp:
            raise InvalidTarget(
                f"({requested[0]}, {requested[1]}) está fuera de la pantalla.",
                hint=(
                    f"Área válida: x={int(bounds.x_min)}..{int(bounds.x_max)}, "
                    f"y={int(bounds.y_min)}..{int(bounds.y_max)}. "
                    "Usa clamp=true para ajustar al borde."
                ),
            )
        return (
            int(round(min(max(requested[0], bounds.x_min), bounds.x_max))),
            int(round(min(max(requested[1], bounds.y_min), bounds.y_max))),
        ), True

    def _check_permission(self, dry_run: bool) -> None:
        if dry_run or self.allow_untrusted:
            return
        trusted = self.backend.accessibility_trusted()
        if trusted is False:
            raise PermissionDenied(
                "El sistema operativo no permite publicar eventos de ratón.",
                hint=self.backend.permission_hint(),
            )

    def _reaction_s(self, style: Style) -> float:
        return self._rng.uniform(*style.reaction_ms) / 1000.0

    def _run_path(
        self,
        path: GeneratedPath,
        *,
        dry_run: bool,
        dragged_button: str | None = None,
    ) -> None:
        if dry_run:
            return
        start = time.perf_counter()
        for point in path.points:
            if self._stop.is_set():
                raise MotionAborted(
                    "Movimiento cancelado con stop.",
                    hint="El cursor se queda donde estaba al cancelar.",
                )
            target = start + point.t
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            self.backend.move(
                int(round(point.x)),
                int(round(point.y)),
                dragged_button=dragged_button,
            )

    def _move_locked(
        self,
        x: float,
        y: float,
        *,
        style: str,
        duration_s: float | None,
        jitter: float,
        curvature: float,
        overshoot: bool | None,
        clamp: bool,
        dry_run: bool,
        settle: bool = True,
        speed_scale: float | None = None,
    ) -> dict:
        style_cfg = self._style(style)
        target, clamped = self._resolve_target(x, y, clamp)
        bounds = self.backend.bounds()
        start = self.backend.position()

        path = build_path(
            (float(start[0]), float(start[1])),
            (float(target[0]), float(target[1])),
            style=style_cfg,
            duration_s=duration_s,
            seed=self.seed,
            jitter=jitter,
            curvature=curvature,
            overshoot=overshoot,
            bounds=bounds,
            speed_scale=speed_scale if speed_scale is not None else self.speed_scale,
            max_duration_s=self.max_duration_s,
            settle=settle,
        )

        if len(path.points) > MAX_STEPS_PER_MOVE:
            raise HumanMouseError(
                f"La trayectoria tendría {len(path.points)} pasos, demasiados."
            )

        final_position = None
        if not dry_run:
            time.sleep(self._reaction_s(style_cfg))
            self._run_path(path, dry_run=False)
            final_position = self.backend.position()

        payload = {
            "ok": True,
            "action": "move",
            "style": path.style,
            "dry_run": dry_run,
            "clamped": clamped,
            "requested": {"x": int(round(float(x))), "y": int(round(float(y)))},
            "from": {"x": int(start[0]), "y": int(start[1])},
            "to": {"x": target[0], "y": target[1]},
            "distance_px": round(path.distance_px, 1),
            "overshoot_px": round(path.overshoot_px, 1),
            "duration_s": round(path.duration_s, 3),
            "steps": len(path.points),
            "backend": self.backend.name,
            "final_position": (
                {"x": int(final_position[0]), "y": int(final_position[1])}
                if final_position is not None
                else None
            ),
            "landed_at_target": (
                abs(final_position[0] - target[0]) <= 1
                and abs(final_position[1] - target[1]) <= 1
                if final_position is not None
                else None
            ),
        }
        payload.update(path.stats())
        return payload

    # -- herramientas públicas -------------------------------------------
    def move(
        self,
        x: float,
        y: float,
        *,
        style: str = "natural",
        duration_s: float | None = None,
        jitter: float = 1.0,
        curvature: float = 1.0,
        overshoot: bool | None = None,
        clamp: bool = True,
        dry_run: bool | None = None,
        settle: bool = True,
    ) -> dict:
        dry = self.dry_run if dry_run is None else dry_run
        with self._motion():
            self._check_permission(dry)
            return self._move_locked(
                x,
                y,
                style=style,
                duration_s=duration_s,
                jitter=jitter,
                curvature=curvature,
                overshoot=overshoot,
                clamp=clamp,
                dry_run=dry,
                settle=settle,
            )

    def click(
        self,
        x: float | None = None,
        y: float | None = None,
        *,
        button: str = "left",
        clicks: int = 1,
        style: str = "natural",
        duration_s: float | None = None,
        clamp: bool = True,
        dry_run: bool | None = None,
        interval_ms: float | None = None,
    ) -> dict:
        if (x is None) != (y is None):
            raise InvalidTarget("Pasa x e y juntos, o ninguno de los dos.")
        if button not in {"left", "right", "middle"}:
            raise InvalidTarget("Botón no válido.", hint="Usa left, right o middle.")
        if not 1 <= int(clicks) <= 3:
            raise InvalidTarget("clicks debe estar entre 1 y 3.")

        dry = self.dry_run if dry_run is None else dry_run
        with self._motion():
            self._check_permission(dry)
            approach = None
            if x is not None and y is not None:
                approach = self._move_locked(
                    x,
                    y,
                    style=style,
                    duration_s=duration_s,
                    jitter=1.0,
                    curvature=1.0,
                    overshoot=None,
                    clamp=clamp,
                    dry_run=dry,
                )

            position = self.backend.position()
            if not dry:
                for index in range(1, int(clicks) + 1):
                    press_s = self._rng.uniform(0.055, 0.115)
                    self.backend.press(button, click_state=index)
                    time.sleep(press_s)
                    self.backend.release(button, click_state=index)
                    if index < clicks:
                        gap = (
                            interval_ms / 1000.0
                            if interval_ms is not None
                            else self._rng.uniform(0.060, 0.130)
                        )
                        time.sleep(max(0.0, gap))
                time.sleep(self._rng.uniform(0.030, 0.090))

            return {
                "ok": True,
                "action": "click",
                "button": button,
                "clicks": int(clicks),
                "dry_run": dry,
                "position": {"x": int(position[0]), "y": int(position[1])},
                "approach": approach,
            }

    def drag(
        self,
        to_x: float,
        to_y: float,
        *,
        from_x: float | None = None,
        from_y: float | None = None,
        button: str = "left",
        style: str = "natural",
        duration_s: float | None = None,
        clamp: bool = True,
        dry_run: bool | None = None,
    ) -> dict:
        if (from_x is None) != (from_y is None):
            raise InvalidTarget("Pasa from_x y from_y juntos, o ninguno.")
        if button not in {"left", "right", "middle"}:
            raise InvalidTarget("Botón no válido.", hint="Usa left, right o middle.")

        dry = self.dry_run if dry_run is None else dry_run
        with self._motion():
            self._check_permission(dry)
            approach = None
            if from_x is not None and from_y is not None:
                approach = self._move_locked(
                    from_x,
                    from_y,
                    style=style,
                    duration_s=None,
                    jitter=1.0,
                    curvature=1.0,
                    overshoot=None,
                    clamp=clamp,
                    dry_run=dry,
                )

            style_cfg = self._style(style)
            target, clamped = self._resolve_target(to_x, to_y, clamp)
            start = self.backend.position()
            path = build_path(
                (float(start[0]), float(start[1])),
                (float(target[0]), float(target[1])),
                style=style_cfg,
                duration_s=duration_s,
                seed=self.seed,
                jitter=1.0,
                curvature=0.8,
                overshoot=False,
                bounds=self.backend.bounds(),
                speed_scale=self.speed_scale,
                max_duration_s=self.max_duration_s,
            )

            pressed = False
            try:
                if not dry:
                    time.sleep(self._rng.uniform(0.060, 0.140))
                    self.backend.press(button, click_state=1)
                    pressed = True
                    time.sleep(self._rng.uniform(0.050, 0.120))
                    self._run_path(path, dry_run=False, dragged_button=button)
                    time.sleep(self._rng.uniform(0.050, 0.120))
                payload = {
                    "ok": True,
                    "action": "drag",
                    "button": button,
                    "dry_run": dry,
                    "clamped": clamped,
                    "requested": {
                        "x": int(round(float(to_x))),
                        "y": int(round(float(to_y))),
                    },
                    "from": {"x": int(start[0]), "y": int(start[1])},
                    "to": {"x": target[0], "y": target[1]},
                    "distance_px": round(path.distance_px, 1),
                    "duration_s": round(path.duration_s, 3),
                    "steps": len(path.points),
                    "approach": approach,
                }
                payload.update(path.stats())
                return payload
            finally:
                if pressed:
                    try:
                        self.backend.release(button, click_state=1)
                    except Exception:
                        pass

    def scroll(
        self,
        amount: int,
        *,
        x: float | None = None,
        y: float | None = None,
        style: str = "natural",
        clamp: bool = True,
        dry_run: bool | None = None,
    ) -> dict:
        if (x is None) != (y is None):
            raise InvalidTarget("Pasa x e y juntos, o ninguno.")
        amount = int(amount)
        if amount == 0:
            raise InvalidTarget("amount no puede ser 0; positivo = arriba.")
        if abs(amount) > 60:
            raise InvalidTarget("amount máximo: 60 líneas por llamada.")

        dry = self.dry_run if dry_run is None else dry_run
        with self._motion():
            self._check_permission(dry)
            approach = None
            if x is not None and y is not None:
                approach = self._move_locked(
                    x,
                    y,
                    style=style,
                    duration_s=None,
                    jitter=1.0,
                    curvature=1.0,
                    overshoot=None,
                    clamp=clamp,
                    dry_run=dry,
                )

            direction = 1 if amount > 0 else -1
            remaining = abs(amount)
            chunks: list[int] = []
            if not dry:
                time.sleep(self._rng.uniform(0.030, 0.090))
                while remaining > 0:
                    if self._stop.is_set():
                        raise MotionAborted("Desplazamiento cancelado con stop.")
                    chunk = min(remaining, self._rng.randint(1, 5))
                    self.backend.scroll(0, direction * chunk)
                    chunks.append(direction * chunk)
                    remaining -= chunk
                    if remaining > 0:
                        time.sleep(self._rng.uniform(0.040, 0.160))
                time.sleep(self._rng.uniform(0.030, 0.100))
            else:
                while remaining > 0:
                    chunk = min(remaining, self._rng.randint(1, 5))
                    chunks.append(direction * chunk)
                    remaining -= chunk

            return {
                "ok": True,
                "action": "scroll",
                "requested_amount": amount,
                "chunks": chunks,
                "total": sum(chunks),
                "dry_run": dry,
                "approach": approach,
            }

    def capture(
        self,
        duration_s: float = 5.0,
        sample_hz: float = 60.0,
        *,
        include_samples: bool = True,
    ) -> dict:
        duration_s = float(duration_s)
        sample_hz = float(sample_hz)
        if not 0.2 <= duration_s <= 60.0:
            raise InvalidTarget("duration_s debe estar entre 0.2 y 60 segundos.")
        if not 10.0 <= sample_hz <= 240.0:
            raise InvalidTarget("sample_hz debe estar entre 10 y 240.")
        if duration_s * sample_hz > 20_000:
            raise InvalidTarget("Demasiadas muestras; baja duration_s o sample_hz.")

        with self._motion():
            backend = self.backend
            t0 = time.perf_counter()
            period = 1.0 / sample_hz
            next_tick = t0
            samples: list[dict] = []
            events: list[dict] = []
            prev_buttons: set[str] | None = None
            buttons_supported = True
            aborted = False

            while True:
                now = time.perf_counter()
                elapsed = now - t0
                if elapsed > duration_s:
                    break
                if self._stop.is_set():
                    aborted = True
                    break

                x, y = backend.position()
                buttons = backend.buttons_down()
                if buttons is None:
                    buttons_supported = False
                    buttons_list: list[str] | None = None
                else:
                    buttons_list = sorted(buttons)
                    if prev_buttons is not None:
                        for name in sorted(buttons - prev_buttons):
                            events.append(
                                {"t": round(elapsed, 4), "type": "down", "button": name}
                            )
                        for name in sorted(prev_buttons - buttons):
                            events.append(
                                {"t": round(elapsed, 4), "type": "up", "button": name}
                            )
                    prev_buttons = set(buttons)

                samples.append(
                    {
                        "t": round(elapsed, 4),
                        "x": int(x),
                        "y": int(y),
                        "buttons": buttons_list,
                    }
                )
                next_tick += period
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

            length = 0.0
            max_speed = 0.0
            speed_sum = 0.0
            speed_n = 0
            for a, b in zip(samples, samples[1:]):
                dt = b["t"] - a["t"]
                if dt <= 0:
                    continue
                segment = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                length += segment
                speed = segment / dt
                max_speed = max(max_speed, speed)
                speed_sum += speed
                speed_n += 1

            result: dict = {
                "ok": True,
                "action": "capture",
                "dry_run": self.dry_run,
                "duration_s": round(duration_s, 3),
                "sample_hz": sample_hz,
                "samples_count": len(samples),
                "buttons_supported": buttons_supported,
                "events": events,
                "aborted": aborted,
                "start": samples[0] if samples else None,
                "end": samples[-1] if samples else None,
                "path_length_px": round(length, 1),
                "max_speed_px_s": round(max_speed, 1),
                "mean_speed_px_s": round(speed_sum / speed_n, 1) if speed_n else 0.0,
            }
            if include_samples:
                result["samples"] = samples
            return result

    def request_permission(self) -> dict:
        backend = self.backend
        request = getattr(backend, "request_access", None)
        granted = request() if callable(request) else None
        trusted = backend.accessibility_trusted()
        return {
            "ok": True,
            "action": "request_permission",
            "granted": granted,
            "trusted": trusted,
            "can_move": trusted is not False or self.allow_untrusted,
            "hint": (
                "Permiso concedido."
                if trusted is True
                else backend.permission_hint()
            ),
        }

    def state(self) -> dict:
        backend = self.backend
        x, y = backend.position()
        buttons = backend.buttons_down()
        bounds = backend.bounds()
        return {
            "ok": True,
            "action": "state",
            "position": {"x": int(x), "y": int(y)},
            "buttons_down": sorted(buttons) if buttons is not None else None,
            "buttons_supported": buttons is not None,
            "bounds": bounds.as_dict(),
            "displays": [display.as_dict() for display in backend.displays()],
            "dry_run": self.dry_run,
            "backend": backend.name,
        }

    def stop(self) -> dict:
        was_moving = self._lock.locked()
        self._stop.set()
        return {
            "ok": True,
            "action": "stop",
            "was_moving": was_moving,
            "message": (
                "Señal de parada enviada; el movimiento se detendrá en el próximo paso."
                if was_moving
                else "No había ningún movimiento en curso."
            ),
        }

    def diagnostics(self) -> dict:
        backend = self.backend
        try:
            x, y = backend.position()
            position = {"x": int(x), "y": int(y)}
            displays = [display.as_dict() for display in backend.displays()]
            bounds: dict | None = backend.bounds().as_dict()
        except Exception as exc:  # pragma: no cover - defensivo
            position = None
            displays = []
            bounds = None
            position_error = str(exc)
        else:
            position_error = None

        trusted = backend.accessibility_trusted()
        return {
            "ok": True,
            "action": "diagnostics",
            "platform": backend.platform,
            "backend": backend.name,
            "position": position,
            "bounds": bounds,
            "displays": displays,
            "position_error": position_error,
            "accessibility": {
                "trusted": trusted,
                "can_move": trusted is not False or self.allow_untrusted,
                "hint": (
                    "Permiso concedido."
                    if trusted is True
                    else backend.permission_hint()
                ),
            },
            "settings": {
                "dry_run": self.dry_run,
                "allow_untrusted": self.allow_untrusted,
                "speed_scale": self.speed_scale,
                "max_duration_s": self.max_duration_s,
                "seed": self.seed,
            },
            "styles": available_styles(),
            "limits": {
                "max_duration_s": self.max_duration_s,
                "max_clicks": 3,
                "max_scroll_lines": 60,
                "capture_max_s": 60,
                "capture_max_hz": 240,
            },
        }

    def close(self) -> None:
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                pass
