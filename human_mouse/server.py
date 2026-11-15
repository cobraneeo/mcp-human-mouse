"""Servidor MCP (stdio) para controlar el ratón con movimiento humano.

Herramientas expuestas:
  mouse_state       lectura de posición, botones, pantallas
  move_human        mover el cursor con trayectoria humana
  click_human       clic (simple, doble o triple) con aproximación humana
  drag_human        arrastrar con el botón pulsado
  scroll_human      desplazamiento por pasos irregulares
  capture_trace     grabar una traza de posición/botones
  stop_motion       cancelar el movimiento en curso
  diagnostics       estado del backend y permisos
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .engine import HumanMouse, HumanMouseError

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("human-mouse")

mcp = FastMCP(
    "human-mouse",
    instructions=(
        "Control del ratón con cinemática humana. Antes de mover, llama a "
        "diagnostics para comprobar la pantalla y el permiso de Accesibilidad. "
        "Las coordenadas están en puntos (no píxeles físicos) y el origen es la "
        "esquina superior izquierda del monitor principal; los monitores a la "
        "izquierda o arriba tienen coordenadas negativas. Usa move_human para "
        "desplazamientos normales, click_human para pulsar, drag_human para "
        "arrastrar y scroll_human para la rueda. dry_run=true simula sin mover."
    ),
)

engine = HumanMouse()


def _safe(call, *args, **kwargs) -> dict[str, Any]:
    try:
        return call(*args, **kwargs)
    except HumanMouseError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "code": exc.code,
            "hint": exc.hint,
        }


async def _run(call, *args, **kwargs) -> dict[str, Any]:
    """Ejecuta una operación larga fuera del event loop.

    Así ``stop_motion`` puede atender una petición concurrente mientras el
    hilo de movimiento sigue publicando eventos.
    """

    return await asyncio.to_thread(_safe, call, *args, **kwargs)


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------
@mcp.tool()
def mouse_state() -> dict[str, Any]:
    """Devuelve posición del cursor, botones pulsados, área de pantalla y monitores.

    Úsala para saber dónde está el ratón antes de mover o para interpretar
    coordenadas en sistemas con varios monitores.
    """

    return _safe(engine.state)


@mcp.tool()
async def move_human(
    x: Annotated[float, Field(description="Coordenada X destino, en puntos de pantalla.")],
    y: Annotated[float, Field(description="Coordenada Y destino, en puntos de pantalla.")],
    style: Annotated[
        Literal["natural", "fast", "precise", "slow"],
        Field(description="Perfil de movimiento: natural, fast, precise o slow."),
    ] = "natural",
    duration_s: Annotated[
        float | None,
        Field(
            description="Duración total aproximada en segundos. Si se omite, se calcula con la ley de Fitts.",
            ge=0.03,
            le=30.0,
        ),
    ] = None,
    jitter: Annotated[
        float,
        Field(description="Multiplicador del temblor (0 = sin temblor, 1 = normal).", ge=0.0, le=3.0),
    ] = 1.0,
    curvature: Annotated[
        float,
        Field(description="Multiplicador de la curvatura del trayecto (0 = recto).", ge=0.0, le=3.0),
    ] = 1.0,
    overshoot: Annotated[
        bool | None,
        Field(description="Forzar (true) o desactivar (false) el sobrepaso; null = automático."),
    ] = None,
    clamp: Annotated[
        bool,
        Field(description="Si el destino está fuera de pantalla, ajustarlo al borde en vez de fallar."),
    ] = True,
    dry_run: Annotated[
        bool | None,
        Field(description="Simula la trayectoria sin publicar eventos. null usa la configuración del servidor."),
    ] = None,
) -> dict[str, Any]:
    """Mueve el cursor hasta (x, y) imitando un movimiento humano real.

    Genera una curva suave con perfil de mínima sacudida, temblor de baja
    amplitud, posible sobrepaso y corrección final. No es un salto instantáneo:
    el movimiento dura entre ~0,2 y ~1,5 s según la distancia y el estilo.

    Devuelve el origen, el destino, la duración, el número de pasos y la
    velocidad máxima estimada. Con dry_run=true no mueve nada y solo calcula.
    """

    return await _run(
        engine.move,
        x,
        y,
        style=style,
        duration_s=duration_s,
        jitter=jitter,
        curvature=curvature,
        overshoot=overshoot,
        clamp=clamp,
        dry_run=dry_run,
    )


@mcp.tool()
async def click_human(
    x: Annotated[
        float | None,
        Field(description="Coordenada X donde pulsar. Si se omite, pulsa en la posición actual."),
    ] = None,
    y: Annotated[
        float | None,
        Field(description="Coordenada Y donde pulsar. Si se omite, pulsa en la posición actual."),
    ] = None,
    button: Annotated[
        Literal["left", "right", "middle"],
        Field(description="Botón del ratón."),
    ] = "left",
    clicks: Annotated[
        int,
        Field(description="Número de clics: 1, 2 (doble) o 3 (triple).", ge=1, le=3),
    ] = 1,
    style: Annotated[
        Literal["natural", "fast", "precise", "slow"],
        Field(description="Perfil del movimiento de aproximación."),
    ] = "natural",
    duration_s: Annotated[
        float | None,
        Field(description="Duración de la aproximación en segundos (opcional).", ge=0.03, le=30.0),
    ] = None,
    interval_ms: Annotated[
        float | None,
        Field(description="Separación entre clics en ms; null = 60-130 ms aleatorio.", ge=20.0, le=400.0),
    ] = None,
    clamp: Annotated[
        bool,
        Field(description="Ajustar al borde si las coordenadas están fuera de pantalla."),
    ] = True,
    dry_run: Annotated[
        bool | None,
        Field(description="Simula sin pulsar ni mover. null usa la configuración del servidor."),
    ] = None,
) -> dict[str, Any]:
    """Hace clic (o doble/triple clic) con aproximación y timing humanos.

    Si se indican x e y, primero se acerca el cursor con una trayectoria humana.
    La presión del botón dura 55-115 ms y los clics múltiples se separan
    60-130 ms, dentro del umbral de doble clic del sistema.
    """

    return await _run(
        engine.click,
        x,
        y,
        button=button,
        clicks=clicks,
        style=style,
        duration_s=duration_s,
        interval_ms=interval_ms,
        clamp=clamp,
        dry_run=dry_run,
    )


@mcp.tool()
async def drag_human(
    to_x: Annotated[float, Field(description="Coordenada X final del arrastre.")],
    to_y: Annotated[float, Field(description="Coordenada Y final del arrastre.")],
    from_x: Annotated[
        float | None,
        Field(description="Coordenada X inicial. Si se omite, se arrastra desde la posición actual."),
    ] = None,
    from_y: Annotated[
        float | None,
        Field(description="Coordenada Y inicial. Si se omite, se arrastra desde la posición actual."),
    ] = None,
    button: Annotated[
        Literal["left", "right", "middle"],
        Field(description="Botón que se mantiene pulsado."),
    ] = "left",
    style: Annotated[
        Literal["natural", "fast", "precise", "slow"],
        Field(description="Perfil del movimiento de arrastre."),
    ] = "natural",
    duration_s: Annotated[
        float | None,
        Field(description="Duración del arrastre en segundos (opcional).", ge=0.05, le=30.0),
    ] = None,
    clamp: Annotated[
        bool,
        Field(description="Ajustar al borde si el destino está fuera de pantalla."),
    ] = True,
    dry_run: Annotated[
        bool | None,
        Field(description="Simula sin pulsar ni mover. null usa la configuración del servidor."),
    ] = None,
) -> dict[str, Any]:
    """Arrastra desde un punto hasta otro manteniendo pulsado el botón.

    Si se indica from_x/from_y, primero acerca el cursor allí con movimiento
    humano. Después pulsa, arrastra con una trayectoria curvada y suelta.
    Siempre suelta el botón, incluso si el movimiento se cancela.
    """

    return await _run(
        engine.drag,
        to_x,
        to_y,
        from_x=from_x,
        from_y=from_y,
        button=button,
        style=style,
        duration_s=duration_s,
        clamp=clamp,
        dry_run=dry_run,
    )


@mcp.tool()
async def scroll_human(
    amount: Annotated[
        int,
        Field(
            description="Líneas a desplazar. Positivo = arriba, negativo = abajo. Máximo 60.",
            ge=-60,
            le=60,
        ),
    ],
    x: Annotated[
        float | None,
        Field(description="Coordenada X donde colocar el cursor antes de desplazar (opcional)."),
    ] = None,
    y: Annotated[
        float | None,
        Field(description="Coordenada Y donde colocar el cursor antes de desplazar (opcional)."),
    ] = None,
    style: Annotated[
        Literal["natural", "fast", "precise", "slow"],
        Field(description="Perfil del movimiento de aproximación."),
    ] = "natural",
    clamp: Annotated[
        bool,
        Field(description="Ajustar al borde si las coordenadas están fuera de pantalla."),
    ] = True,
    dry_run: Annotated[
        bool | None,
        Field(description="Simula sin mover ni desplazar. null usa la configuración del servidor."),
    ] = None,
) -> dict[str, Any]:
    """Desplaza la rueda en varios golpes irregulares, como una mano humana.

    En lugar de un único evento grande, reparte `amount` en bloques de 1-5
    líneas con pausas de 40-160 ms. Positivo = hacia arriba.
    """

    return await _run(
        engine.scroll,
        amount,
        x=x,
        y=y,
        style=style,
        clamp=clamp,
        dry_run=dry_run,
    )


@mcp.tool()
async def capture_trace(
    duration_s: Annotated[
        float,
        Field(description="Duración de la captura en segundos (0,2-60).", ge=0.2, le=60.0),
    ] = 5.0,
    sample_hz: Annotated[
        float,
        Field(description="Frecuencia de muestreo en Hz (10-240).", ge=10.0, le=240.0),
    ] = 60.0,
    include_samples: Annotated[
        bool,
        Field(description="Incluir la lista completa de muestras en la respuesta."),
    ] = True,
) -> dict[str, Any]:
    """Graba la posición del cursor y los botones durante un intervalo.

    Devuelve muestras {t, x, y, buttons}, transiciones de botón y estadísticas
    de distancia y velocidad. Sirve para analizar un movimiento real o para
    reutilizar su forma. No necesita permiso de Accesibilidad para leer.
    """

    return await _run(
        engine.capture,
        duration_s,
        sample_hz,
        include_samples=include_samples,
    )


@mcp.tool()
async def request_permission() -> dict[str, Any]:
    """Solicita al sistema permiso para publicar eventos de ratón.

    En macOS muestra el diálogo de Accesibilidad (TCC) para la aplicación que
    lanza el servidor. Si el diálogo no aparece, hay que añadir la app a mano
    en Ajustes del Sistema → Privacidad y seguridad → Accesibilidad. Después
    reinicia el servidor MCP. En Windows y Linux no hace falta.
    """

    return await _run(engine.request_permission)


@mcp.tool()
def stop_motion() -> dict[str, Any]:
    """Cancela el movimiento en curso en el siguiente paso de la trayectoria.

    El cursor se queda donde esté en ese instante. Si no hay movimiento,
    devuelve was_moving=false.
    """

    return _safe(engine.stop)


@mcp.tool()
def diagnostics() -> dict[str, Any]:
    """Comprueba backend, pantallas, posición y permiso de Accesibilidad.

    Llama a esta herramienta primero. En macOS, si accessibility.trusted es
    false, hay que conceder Accesibilidad a la app que lanza el servidor y
    reiniciarlo. También muestra los estilos y límites disponibles.
    """

    return _safe(engine.diagnostics)


def main() -> None:
    log.info("Iniciando servidor MCP human-mouse (stdio)")
    try:
        mcp.run()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
