"""Pruebas del generador de trayectorias (sin tocar el ratón)."""

from __future__ import annotations

import math

import pytest

from human_mouse.trajectory import (
    STYLES,
    Bounds,
    build_path,
    fitts_duration,
    min_jerk,
)


def test_min_jerk_extremos_y_monotonia() -> None:
    assert min_jerk(0.0) == pytest.approx(0.0)
    assert min_jerk(1.0) == pytest.approx(1.0)
    valores = [min_jerk(i / 100) for i in range(101)]
    assert all(b >= a for a, b in zip(valores, valores[1:]))


@pytest.mark.parametrize("style", list(STYLES))
def test_origen_y_destino_exactos(style: str) -> None:
    path = build_path((100.0, 200.0), (900.0, 600.0), style=style, seed=7)
    assert (path.points[0].x, path.points[0].y) == (100.0, 200.0)
    assert (path.points[-1].x, path.points[-1].y) == (900.0, 600.0)


@pytest.mark.parametrize("style", list(STYLES))
def test_tiempos_estrictamente_crecientes(style: str) -> None:
    path = build_path((10.0, 10.0), (800.0, 500.0), style=style, seed=3)
    tiempos = [p.t for p in path.points]
    assert tiempos[0] == 0.0
    assert all(b > a for a, b in zip(tiempos, tiempos[1:]))
    assert path.duration_s == pytest.approx(tiempos[-1])


def test_estilos_ordenan_la_duracion() -> None:
    start, end = (0.0, 0.0), (1000.0, 0.0)
    fast = build_path(start, end, style="fast", seed=1).duration_s
    natural = build_path(start, end, style="natural", seed=1).duration_s
    slow = build_path(start, end, style="slow", seed=1).duration_s
    assert fast < natural < slow


def test_duracion_explicita_se_respeta_aproximadamente() -> None:
    path = build_path((0.0, 0.0), (500.0, 300.0), duration_s=0.8, seed=2, settle=False)
    assert path.duration_s == pytest.approx(0.8, abs=0.01)


def test_sin_jitter_ni_curvatura_la_trayectoria_es_recta() -> None:
    start, end = (50.0, 60.0), (650.0, 360.0)
    path = build_path(
        start,
        end,
        jitter=0.0,
        curvature=0.0,
        overshoot=False,
        seed=11,
        settle=False,
    )
    dx, dy = end[0] - start[0], end[1] - start[1]
    norma = math.hypot(dx, dy)
    desviaciones = [
        abs(dx * (p.y - start[1]) - dy * (p.x - start[0])) / norma
        for p in path.points
    ]
    assert max(desviaciones) < 0.01


def test_sobrepaso_forzado_genera_correccion() -> None:
    path = build_path(
        (100.0, 100.0),
        (900.0, 100.0),
        overshoot=True,
        seed=5,
        settle=False,
    )
    assert path.overshoot_px > 0.5
    # Debe existir un punto más allá del destino y luego volver.
    xs = [p.x for p in path.points]
    assert max(xs) > 900.0
    assert path.points[-1].x == 900.0


def test_sobrepaso_desactivado_no_pasa_del_destino() -> None:
    path = build_path(
        (100.0, 100.0),
        (900.0, 100.0),
        overshoot=False,
        curvature=0.0,
        jitter=0.0,
        seed=5,
        settle=False,
    )
    assert path.overshoot_px == 0.0
    assert max(p.x for p in path.points) <= 900.0 + 1e-9


def test_misma_semilla_misma_trayectoria() -> None:
    a = build_path((0.0, 0.0), (400.0, 300.0), seed=99)
    b = build_path((0.0, 0.0), (400.0, 300.0), seed=99)
    assert [(p.x, p.y, p.t) for p in a.points] == [(p.x, p.y, p.t) for p in b.points]


def test_semillas_distintas_cambian_la_forma() -> None:
    a = build_path((0.0, 0.0), (400.0, 300.0), seed=1)
    b = build_path((0.0, 0.0), (400.0, 300.0), seed=2)
    assert [(p.x, p.y) for p in a.points] != [(p.x, p.y) for p in b.points]


def test_limites_de_pantalla() -> None:
    bounds = Bounds(0, 0, 1919, 1079)
    path = build_path(
        (10.0, 10.0),
        (1900.0, 1070.0),
        bounds=bounds,
        overshoot=True,
        seed=4,
    )
    assert all(0 <= p.x <= 1919 and 0 <= p.y <= 1079 for p in path.points)


def test_movimiento_casi_nulo() -> None:
    path = build_path((100.0, 100.0), (100.2, 100.1), seed=1)
    assert path.points[0].x == 100.0
    assert path.points[-1].x == 100.2
    assert path.duration_s > 0


def test_estilo_invalido() -> None:
    with pytest.raises(ValueError, match="Estilo desconocido"):
        build_path((0.0, 0.0), (10.0, 10.0), style="teleport")


def test_duracion_fitts_crece_con_la_distancia() -> None:
    import random

    rng = random.Random(1)
    corta = fitts_duration(50.0, STYLES["natural"], rng)
    larga = fitts_duration(1500.0, STYLES["natural"], rng)
    assert corta < larga


def test_estadisticas_coherentes() -> None:
    path = build_path((0.0, 0.0), (600.0, 400.0), seed=8)
    stats = path.stats()
    assert stats["path_length_px"] >= path.distance_px - 1.0
    assert stats["max_speed_px_s"] >= stats["mean_speed_px_s"] > 0
