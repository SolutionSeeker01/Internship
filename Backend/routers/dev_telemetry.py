# Backend/routers/dev_telemetry.py
"""
Developer Telemetry WebSocket Router — Dev-Only Event Bridge

Exposes a developer-only WebSocket endpoint at `WS /api/v1/dev/telemetry` that
subscribes to global_event_bus and streams RuntimeEvent JSON payloads live to
external developer tools (such as validation_console.py).

Constraints:
  - RuntimeEventBus remains 100% transport-agnostic (unaware of WebSockets).
  - Dev-only endpoint (can be conditionally mounted or removed).
  - Read-only stream; clients cannot trigger backend operations.
"""

import asyncio
import json
from typing import Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from dev_tools.drm import global_event_bus, RuntimeEvent
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/dev", tags=["Developer Telemetry"])

# In-memory active developer WebSocket clients set
_active_ws_clients: Set[WebSocket] = set()
_bus_subscribed = False
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def _on_bus_event(event: RuntimeEvent) -> None:
    """
    Passive subscriber callback invoked by RuntimeEventBus worker thread.
    Schedules JSON broadcast to connected WebSocket clients on the main asyncio loop.
    """
    if not _active_ws_clients or _main_loop is None or not _main_loop.is_running():
        return

    event_dict = event.to_dict()
    # Schedule thread-safe async broadcast on main event loop
    asyncio.run_coroutine_threadsafe(_broadcast_event(event_dict), _main_loop)


async def _broadcast_event(event_dict: dict) -> None:
    """Broadcasts event dictionary to all active WebSocket clients."""
    if not _active_ws_clients:
        return

    message_text = json.dumps(event_dict)
    disconnected_clients = set()

    for ws in list(_active_ws_clients):
        try:
            await ws.send_text(message_text)
        except Exception:
            disconnected_clients.add(ws)

    # Clean up stale connections
    for ws in disconnected_clients:
        _active_ws_clients.discard(ws)


@router.websocket("/telemetry")
async def dev_telemetry_websocket(websocket: WebSocket):
    """
    Developer Telemetry WebSocket connection handler.
    Streams RuntimeEvent telemetry live to connected developer tools.
    """
    global _bus_subscribed, _main_loop
    await websocket.accept()

    # Capture main event loop reference for thread-safe cross-thread dispatch
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()

    _active_ws_clients.add(websocket)
    logger.info(f"Developer Telemetry WS client connected. Total active clients: {len(_active_ws_clients)}")

    # Ensure bus subscription is active
    if not _bus_subscribed:
        global_event_bus.subscribe(_on_bus_event)
        _bus_subscribed = True

    try:
        # Keep connection open until client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as err:
        logger.debug(f"Developer Telemetry WS client exception: {err}")
    finally:
        _active_ws_clients.discard(websocket)
        logger.info(f"Developer Telemetry WS client disconnected. Total active clients: {len(_active_ws_clients)}")
