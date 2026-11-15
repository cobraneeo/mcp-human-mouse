"""Generación de trayectorias de ratón con cinemática humana.

La idea es no mover el cursor en línea recta a velocidad constante, sino
reproducir los rasgos que aparecen al medir movimientos reales de una persona:

* perfil de velocidad de mínima sacudida (aceleración y frenada suaves),
* curvatura ligera del trayecto,
* temblor de baja amplitud correlacionado en el tiempo,
* sobrepaso (overshoot) y submovimiento corrector en distancias largas,
* tiempos de reacción y de asentamiento variables.

El módulo es puro Python, sin dependencias del sistema, para poder probarlo
sin mover el ratón de verdad.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bounds:
    """Rectángulo inclusivo en coordenadas de pantalla."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min + 1.0

    @property
    def height(self) -> float:
        return self.y_max - self.y_min + 1.0

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def clamp(self, x: float, y: float) -> Point:
        return (
            min(max(x, self.x_min), self.x_max),
            min(max(y, self.y_min), self.y_max),
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "x_min": self.x_min,
            "y_min": self.y_min,
            "x_max": self.x_max,
            "y_max": self.y_max,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class Style:
    """Parámetros de un estilo de movimiento."""

    name: str
    speed: float
    """Multiplicador de duración: > 1 más lento, < 1 más rápido."""

    jitter_px: float
    curvature_px: float
    overshoot_prob: float
    max_overshoot_px: float
    reaction_ms: tuple[int, int]
    settle_ms: tuple[int, int]
    step_hz: int


STYLES: dict[str, Style] = {
    "natural": Style(
        name="natural",
        speed=1.0,
        jitter_px=0.9,
        curvature_px=26.0,
        overshoot_prob=0.45,
        max_overshoot_px=16.0,
        reaction_ms=(45, 120),
        settle_ms=(25, 70),
        step_hz=120,
    ),
    "fast": Style(
        name="fast",
        speed=0.62,
        jitter_px=1.2,
        curvature_px=34.0,
        overshoot_prob=0.55,
        max_overshoot_px=22.0,
        reaction_ms=(20, 60),
        settle_ms=(15, 40),
        step_hz=120,
    ),
    "precise": Style(
        name="precise",
        speed=1.25,
        jitter_px=0.35,
        curvature_px=12.0,
        overshoot_prob=0.0,
        max_overshoot_px=0.0,
        reaction_ms=(80, 160),
        settle_ms=(50, 110),
        step_hz=144,
    ),
    "slow": Style(
        name="slow",
        speed=1.7,
        jitter_px=0.7,
        curvature_px=20.0,
        overshoot_prob=0.15,
        max_overshoot_px=8.0,
        reaction_ms=(120, 240),
        settle_ms=(60, 120),
        step_hz=100,
    ),
}


@dataclass(frozen=True)
class PathPoint:
    x: float
    y: float
    t: float
    """Segundos desde el inicio del movimiento."""


@dataclass
class GeneratedPath:
    points: list[PathPoint]
    style: str
    distance_px: float
    overshoot_px: float
    requested_duration_s: float | None

    @property
    def duration_s(self) -> float:
        return self.points[-1].t if self.points else 0.0

    def stats(self) -> dict[str, float]:
        length = 0.0
        max_speed = 0.0
        speed_sum = 0.0
        speed_n = 0
        for a, b in zip(self.points, self.points[1:]):
            dt = b.t - a.t
            if dt <= 0:
                continue
            seg = math.hypot(b.x - a.x, b.y - a.y)
            length += seg
            speed = seg / dt
            max_speed = max(max_speed, speed)
            speed_sum += speed
            speed_n += 1
        return {
            "path_length_px": round(length, 2),
            "max_speed_px_s": round(max_speed, 2),
            "mean_speed_px_s": round(speed_sum / speed_n, 2) if speed_n else 0.0,
        }


# ---------------------------------------------------------------------------
# Utilidades matemáticas
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def min_jerk(t: float) -> float:
    """Perfil de mínima sacudida: s(0)=0, s(1)=1, derivadas 1ª y 2ª nulas."""

    t = _clamp(t, 0.0, 1.0)
    return t * t * t * (10.0 + t * (-15.0 + 6.0 * t))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3.0 * mt * mt * t
    c = 3.0 * mt * t * t
    d = t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def fitts_duration(distance_px: float, style: Style, rng: random.Random) -> float:
    """Duración base según la ley de Fitts, con variabilidad humana."""

    index = math.log2(distance_px / 8.0 + 1.0)
    seconds = (0.12 + 0.11 * index) * style.speed * rng.uniform(0.88, 1.15)
    return _clamp(seconds, 0.18, 2.6)


def available_styles() -> dict[str, dict[str, float | int]]:
    return {
        name: {
            "speed": s.speed,
            "jitter_px": s.jitter_px,
            "curvature_px": s.curvature_px,
            "overshoot_prob": s.overshoot_prob,
            "step_hz": s.step_hz,
        }
        for name, s in STYLES.items()
    }


# ---------------------------------------------------------------------------
# Generador principal
# ---------------------------------------------------------------------------
def _segment(
    start: Point,
    end: Point,
    duration: float,
    start_t: float,
    *,
    style: Style,
    rng: random.Random,
    jitter_scale: float,
    curvature_scale: float,
    bounds: Bounds | None,
    tremor_phase: float,
    tremor_hz: float,
    noise_state: tuple[float, float],
    apply_settle: bool = True,
) -> tuple[list[PathPoint], tuple[float, float]]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance < 0.01:
        point = PathPoint(end[0], end[1], start_t)
        return [point], noise_state

    ux, uy = dx / distance, dy / distance
    px, py = -uy, ux

    # Curvatura: desplazamiento perpendicular de los puntos de control.
    sag = min(style.curvature_px, max(3.0, distance * 0.06)) * curvature_scale
    amplitude = sag * rng.uniform(0.35, 1.0) * rng.choice((-1.0, 1.0))
    along1 = rng.uniform(-2.0, 2.0)
    along2 = rng.uniform(-2.0, 2.0)
    c1 = (
        start[0] + dx * 0.30 + px * amplitude * 0.90 + ux * along1,
        start[1] + dy * 0.30 + py * amplitude * 0.90 + uy * along1,
    )
    c2 = (
        start[0] + dx * 0.66 + px * amplitude * 0.45 + ux * along2,
        start[1] + dy * 0.66 + py * amplitude * 0.45 + uy * along2,
    )

    steps = max(2, round(duration * style.step_hz))
    steps = min(steps, 3000)
    dt = duration / steps

    # Ruido correlacionado (proceso de Ornstein-Uhlenbeck) + tremor periódico.
    sigma = max(0.0, style.jitter_px * jitter_scale)
    tau = 0.055
    alpha = math.exp(-dt / tau) if tau > 0 else 0.0
    step_sigma = sigma * math.sqrt(max(0.0, 1.0 - alpha * alpha))
    nx, ny = noise_state
    tremor_amp = 0.30 * jitter_scale

    points: list[PathPoint] = []
    for i in range(1, steps + 1):
        u = i / steps
        eased = min_jerk(u)
        if i < steps:
            # Pequeña deformación temporal: nunca es un perfil perfecto.
            warp = 0.012 * math.sin(math.pi * u) * math.sin(2.0 * math.pi * 1.3 * u + tremor_phase)
            eased = _clamp(eased + warp, 0.0, 1.0)
        else:
            eased = 1.0

        x, y = _cubic_bezier(start, c1, c2, end, eased)

        nx = nx * alpha + rng.gauss(0.0, step_sigma)
        ny = ny * alpha + rng.gauss(0.0, step_sigma)
        fade = 1.0 - 0.40 * eased
        x += nx * fade
        y += ny * fade

        t_abs = start_t + duration * u
        tremor = tremor_amp * math.sin(2.0 * math.pi * tremor_hz * t_abs + tremor_phase)
        x += tremor * px * 0.6
        y += tremor * py * 0.6

        if i == steps:
            # El destino debe ser exacto: nada de ruido en el último punto.
            x, y = end
        if bounds is not None:
            x, y = bounds.clamp(x, y)
        points.append(PathPoint(x, y, t_abs))

    if apply_settle:
        settle_s = rng.uniform(*style.settle_ms) / 1000.0
        if settle_s > 0.005:
            angle = rng.uniform(0.0, 2.0 * math.pi)
            off = rng.uniform(0.30, 0.85)
            mid_x = end[0] + math.cos(angle) * off
            mid_y = end[1] + math.sin(angle) * off
            if bounds is not None:
                mid_x, mid_y = bounds.clamp(mid_x, mid_y)
            points.append(PathPoint(mid_x, mid_y, points[-1].t + settle_s * 0.45))
            points.append(PathPoint(end[0], end[1], points[-1].t + settle_s * 0.55))

    return points, (nx, ny)


def build_path(
    start: Point,
    end: Point,
    *,
    style: str | Style = "natural",
    duration_s: float | None = None,
    seed: int | None = None,
    jitter: float = 1.0,
    curvature: float = 1.0,
    overshoot: bool | None = None,
    bounds: Bounds | None = None,
    speed_scale: float = 1.0,
    max_duration_s: float = 30.0,
    settle: bool = True,
) -> GeneratedPath:
    """Construye una trayectoria humana entre dos puntos.

    ``duration_s`` fija la duración total (aprox.); si es ``None`` se calcula
    con la ley de Fitts. ``overshoot`` fuerza o desactiva el sobrepaso; con
    ``None`` se decide de forma probabilística según el estilo y la distancia.
    """

    if isinstance(style, str):
        try:
            style_cfg = STYLES[style]
        except KeyError as exc:
            raise ValueError(
                f"Estilo desconocido: {style!r}. Usa uno de: {', '.join(STYLES)}"
            ) from exc
    else:
        style_cfg = style

    if not (math.isfinite(start[0]) and math.isfinite(start[1])):
        raise ValueError("El punto de origen no es válido")
    if not (math.isfinite(end[0]) and math.isfinite(end[1])):
        raise ValueError("El punto de destino no es válido")

    jitter_scale = max(0.0, float(jitter))
    curvature_scale = max(0.0, float(curvature))
    speed_scale = max(0.05, float(speed_scale))

    rng = random.Random(seed)
    distance = math.hypot(end[0] - start[0], end[1] - start[1])

    if duration_s is not None:
        duration = _clamp(float(duration_s), 0.03, max(0.05, max_duration_s))
    else:
        duration = fitts_duration(distance, style_cfg, rng)
        duration = _clamp(duration / speed_scale, 0.03, max(0.05, max_duration_s))

    # Movimientos casi nulos: no merece la pena simular todo.
    if distance < 0.75:
        settle_s = rng.uniform(*style_cfg.settle_ms) / 1000.0 if settle else 0.0
        points = [PathPoint(start[0], start[1], 0.0)]
        points.append(PathPoint(end[0], end[1], max(duration, 0.03)))
        if settle_s > 0.005:
            points.append(PathPoint(end[0], end[1], points[-1].t + settle_s))
        return GeneratedPath(points, style_cfg.name, distance, 0.0, duration_s)

    # Sobrepaso: apuntar un poco más allá y corregir con un submovimiento.
    use_overshoot = False
    if overshoot is True:
        use_overshoot = distance > 40.0
    elif overshoot is None:
        use_overshoot = distance > 180.0 and rng.random() < style_cfg.overshoot_prob
    if style_cfg.max_overshoot_px <= 0:
        use_overshoot = False

    aim = end
    overshoot_px = 0.0
    if use_overshoot:
        ux = (end[0] - start[0]) / distance
        uy = (end[1] - start[1]) / distance
        px, py = -uy, ux
        os_dist = min(style_cfg.max_overshoot_px, max(3.0, distance * 0.035))
        os_dist *= rng.uniform(0.35, 1.0)
        aim = (
            end[0] + ux * os_dist + px * rng.uniform(-1.5, 1.5),
            end[1] + uy * os_dist + py * rng.uniform(-1.5, 1.5),
        )
        if bounds is not None:
            aim = bounds.clamp(*aim)
        overshoot_px = math.hypot(aim[0] - end[0], aim[1] - end[1])
        if overshoot_px < 1.0:
            use_overshoot = False
            aim = end
            overshoot_px = 0.0

    tremor_phase = rng.uniform(0.0, 2.0 * math.pi)
    tremor_hz = rng.uniform(7.5, 11.5)
    points: list[PathPoint] = [PathPoint(start[0], start[1], 0.0)]
    noise_state = (0.0, 0.0)

    if use_overshoot:
        gap = rng.uniform(0.035, 0.080)
        primary_duration = max(0.03, duration * rng.uniform(0.76, 0.86))
        correction_duration = duration - primary_duration - gap
        if correction_duration < 0.04:
            # Si no cabe la corrección, se alarga un poco el gesto.
            correction_duration = 0.06
            primary_duration = max(0.03, duration - gap - correction_duration)
        primary, noise_state = _segment(
            start,
            aim,
            primary_duration,
            0.0,
            style=style_cfg,
            rng=rng,
            jitter_scale=jitter_scale,
            curvature_scale=curvature_scale,
            bounds=bounds,
            tremor_phase=tremor_phase,
            tremor_hz=tremor_hz,
            noise_state=noise_state,
            apply_settle=False,
        )
        points.extend(primary)

        # Micro-pausa al alcanzar el punto de sobrepaso.
        pause_point = PathPoint(points[-1].x, points[-1].y, points[-1].t + gap)
        points.append(pause_point)

        correction, noise_state = _segment(
            aim,
            end,
            correction_duration,
            points[-1].t,
            style=style_cfg,
            rng=rng,
            jitter_scale=jitter_scale * 0.7,
            curvature_scale=curvature_scale * 0.35,
            bounds=bounds,
            tremor_phase=tremor_phase,
            tremor_hz=tremor_hz,
            noise_state=noise_state,
            apply_settle=settle,
        )
        points.extend(correction)
    else:
        segment, _ = _segment(
            start,
            end,
            duration,
            0.0,
            style=style_cfg,
            rng=rng,
            jitter_scale=jitter_scale,
            curvature_scale=curvature_scale,
            bounds=bounds,
            tremor_phase=tremor_phase,
            tremor_hz=tremor_hz,
            noise_state=noise_state,
            apply_settle=settle,
        )
        points.extend(segment)

    # Garantía final: el último punto es exactamente el destino.
    last = points[-1]
    points[-1] = PathPoint(end[0], end[1], last.t)

    return GeneratedPath(
        points=points,
        style=style_cfg.name,
        distance_px=distance,
        overshoot_px=overshoot_px,
        requested_duration_s=duration_s,
    )
