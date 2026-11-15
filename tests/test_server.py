"""Pruebas del servidor MCP: nombres, esquemas y manejo de errores."""

from __future__ import annotations

import asyncio

from human_mouse import server
from human_mouse.engine import HumanMouseError


def _tools():
    return asyncio.run(server.mcp.list_tools())


def test_herramientas_esperadas() -> None:
    nombres = {tool.name for tool in _tools()}
    assert {
        "mouse_state",
        "move_human",
        "click_human",
        "drag_human",
        "scroll_human",
        "capture_trace",
        "request_permission",
        "stop_motion",
        "diagnostics",
    } <= nombres


def test_esquema_de_move_human() -> None:
    tools = {tool.name: tool for tool in _tools()}
    move = tools["move_human"]
    props = move.inputSchema["properties"]
    assert {"x", "y", "style", "duration_s", "jitter", "clamp", "dry_run"} <= set(props)
    assert props["style"]["enum"] == ["natural", "fast", "precise", "slow"]
    assert "Mueve el cursor" in (move.description or "")


def test_safe_convierte_errores_en_resultado() -> None:
    def boom() -> None:
        raise HumanMouseError("algo falló", hint="prueba")

    result = server._safe(boom)
    assert result["ok"] is False
    assert result["code"] == "error"
    assert result["hint"] == "prueba"


def test_diagnostics_responde_sin_mover() -> None:
    result = server.diagnostics()
    assert result["ok"] is True
    assert "accessibility" in result
    assert "displays" in result
    assert "styles" in result
