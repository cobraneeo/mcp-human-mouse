"""Genera el SVG de ejemplo de docs/trayectorias.svg (sin dependencias)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from human_mouse.trajectory import build_path  # noqa: E402

START = (150.0, 420.0)
END = (760.0, 170.0)
COLORS = {
    "natural": "#38bdf8",
    "fast": "#fb923c",
    "precise": "#34d399",
    "slow": "#c084fc",
}
SEEDS = {"natural": 12, "fast": 7, "precise": 3, "slow": 21}


def polyline(points: list[tuple[float, float]]) -> str:
    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points)


def main() -> None:
    paths = {}
    for name in ("slow", "fast", "precise", "natural"):
        paths[name] = build_path(
            START,
            END,
            style=name,
            seed=SEEDS[name],
            overshoot=True if name == "natural" else False,
            curvature=3.0,
            settle=False,
        )

    width, height = 960, 560
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
        '<stop offset="0" stop-color="#0b1220"/>',
        '<stop offset="1" stop-color="#111c31"/>',
        "</linearGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>',
    ]

    for x in range(60, 920, 40):
        out.append(
            f'<line x1="{x}" y1="100" x2="{x}" y2="470" stroke="#1e293b" stroke-width="1"/>'
        )
    for y in range(100, 480, 40):
        out.append(
            f'<line x1="40" y1="{y}" x2="920" y2="{y}" stroke="#1e293b" stroke-width="1"/>'
        )

    out += [
        '<text x="40" y="48" fill="#e2e8f0" font-family="Inter, SF Pro Display, sans-serif" '
        'font-size="24" font-weight="700">Trayectorias humanas sintéticas</text>',
        '<text x="40" y="76" fill="#94a3b8" font-family="Inter, SF Pro Display, sans-serif" '
        'font-size="14">Cuatro gestos hasta el mismo destino · distinta semilla y estilo · '
        'curvatura ×3 para visualizar · el último punto es exacto</text>',
    ]

    for name, path in paths.items():
        coords = [(p.x, p.y) for p in path.points]
        out.append(
            f'<path d="{polyline(coords)}" fill="none" stroke="{COLORS[name]}" '
            'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" '
            'opacity="0.95"/>'
        )

    # Punto de sobrepaso del trazo natural: el más alejado en la dirección.
    natural = paths["natural"]
    dx, dy = END[0] - START[0], END[1] - START[1]
    norm = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / norm, dy / norm
    far = max(natural.points, key=lambda p: (p.x - START[0]) * ux + (p.y - START[1]) * uy)
    if (far.x - START[0]) * ux + (far.y - START[1]) * uy > (END[0] - START[0]) * ux + (
        END[1] - START[1]
    ) * uy:
        out += [
            f'<line x1="{far.x:.1f}" y1="{far.y:.1f}" x2="{END[0]}" y2="{END[1]}" '
            'stroke="#38bdf8" stroke-width="1" stroke-dasharray="3 4" opacity="0.7"/>',
            f'<circle cx="{far.x:.1f}" cy="{far.y:.1f}" r="4.5" fill="none" '
            'stroke="#38bdf8" stroke-width="1.5"/>',
            f'<text x="{far.x - 6:.1f}" y="{far.y - 16:.1f}" fill="#7dd3fc" '
            'font-family="Inter, sans-serif" font-size="11">sobrepaso + corrección</text>',
        ]

    out += [
        f'<circle cx="{START[0]}" cy="{START[1]}" r="6" fill="#64748b"/>',
        f'<circle cx="{START[0]}" cy="{START[1]}" r="11" fill="none" stroke="#64748b" '
        'stroke-width="1" opacity="0.6"/>',
        f'<circle cx="{END[0]}" cy="{END[1]}" r="7" fill="none" stroke="#f8fafc" '
        'stroke-width="2"/>',
        f'<line x1="{END[0] - 12}" y1="{END[1]}" x2="{END[0] + 12}" y2="{END[1]}" '
        'stroke="#f8fafc" stroke-width="1.5"/>',
        f'<line x1="{END[0]}" y1="{END[1] - 12}" x2="{END[0]}" y2="{END[1] + 12}" '
        'stroke="#f8fafc" stroke-width="1.5"/>',
        f'<text x="{END[0] + 18}" y="{END[1] + 24}" fill="#f8fafc" '
        'font-family="Inter, sans-serif" font-size="12">destino exacto</text>',
        f'<text x="{START[0] - 10}" y="{START[1] + 26}" fill="#94a3b8" '
        'font-family="Inter, sans-serif" font-size="12">origen</text>',
    ]

    legend_y = 500
    x = 40
    for name in ("natural", "fast", "precise", "slow"):
        path = paths[name]
        out += [
            f'<line x1="{x}" y1="{legend_y}" x2="{x + 26}" y2="{legend_y}" '
            f'stroke="{COLORS[name]}" stroke-width="3" stroke-linecap="round"/>',
            f'<text x="{x + 34}" y="{legend_y + 4}" fill="#cbd5e1" '
            f'font-family="Inter, sans-serif" font-size="12">{name} · '
            f'{path.duration_s:.2f}s · {len(path.points)} pasos</text>',
        ]
        x += 220

    out.append("</svg>")
    target = Path(__file__).resolve().parents[1] / "docs" / "trayectorias.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
