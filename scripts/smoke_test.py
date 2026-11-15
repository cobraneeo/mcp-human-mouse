"""Prueba de humo del protocolo MCP por stdio.

Lanza el servidor como lo haría un cliente real, lista las herramientas y
ejecuta una simulación (dry_run) sin mover el ratón.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        cwd="/",
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"herramientas: {len(tools.tools)}")
            for tool in tools.tools:
                print(f"  - {tool.name}")

            diag = await session.call_tool("diagnostics", {})
            diag_data = json.loads(diag.content[0].text)
            print(
                "diagnostics:",
                json.dumps(
                    {
                        "ok": diag_data.get("ok"),
                        "backend": diag_data.get("backend"),
                        "position": diag_data.get("position"),
                        "trusted": diag_data.get("accessibility", {}).get("trusted"),
                    },
                    ensure_ascii=False,
                ),
            )

            move = await session.call_tool(
                "move_human",
                {"x": 640, "y": 400, "style": "natural", "dry_run": True},
            )
            move_data = json.loads(move.content[0].text)
            print(
                "move_human:",
                json.dumps(
                    {
                        "ok": move_data.get("ok"),
                        "from": move_data.get("from"),
                        "to": move_data.get("to"),
                        "duration_s": move_data.get("duration_s"),
                        "steps": move_data.get("steps"),
                        "dry_run": move_data.get("dry_run"),
                    },
                    ensure_ascii=False,
                ),
            )

            if not move_data.get("ok"):
                return 1
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
