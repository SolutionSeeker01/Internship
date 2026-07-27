# Backend/dev_tools/validation_console.py
"""
Developer Validation Console (DVC) — Main CLI Entry Point

Connects via WebSocket to `ws://localhost:8000/api/v1/dev/telemetry` (or runs in-process fallback),
subscribes to live RuntimeEvent stream, and renders the terminal cockpit using Rich.

Usage:
    python dev_tools/validation_console.py
"""

import sys
import os
import time
import json
import asyncio
import threading
from datetime import datetime
from rich.live import Live

# Ensure Backend root directory is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dev_tools.drm import global_event_bus, RuntimeEvent
from dev_tools.console import ConsoleState, make_layout

try:
    import websockets
    HAS_WEBSOCKETS_LIB = True
except ImportError:
    HAS_WEBSOCKETS_LIB = False


def _websocket_client_worker(state: ConsoleState, ws_url: str):
    """
    Background worker connecting to dev telemetry WebSocket endpoint and pushing events to ConsoleState.
    """
    async def listen():
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    print(f"Connected to Live Backend Telemetry Stream at {ws_url}\n")
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        # Reconstruct RuntimeEvent object from dict
                        evt = RuntimeEvent(
                            event_type=data.get("event_type", "UNKNOWN"),
                            component=data.get("component", "UNKNOWN"),
                            trade_id=data.get("trade_id"),
                            order_id=data.get("order_id"),
                            severity=data.get("severity", "INFO"),
                            payload=data.get("payload", {}),
                            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now()
                        )
                        state.on_event(evt)
            except Exception:
                # Reconnect attempt after delay
                await asyncio.sleep(1.0)

    asyncio.run(listen())


def run_console():
    """
    Initializes DVC state listener and runs Rich Live rendering loop.
    """
    state = ConsoleState()
    ws_url = os.getenv("DVC_TELEMETRY_WS", "ws://localhost:8000/api/v1/dev/telemetry")

    # 1. Direct in-process fallback subscription
    global_event_bus.subscribe(state.on_event)

    # 2. If websockets library available, start background WebSocket listener thread to connect to uvicorn
    if HAS_WEBSOCKETS_LIB:
        ws_thread = threading.Thread(
            target=_websocket_client_worker,
            args=(state, ws_url),
            daemon=True
        )
        ws_thread.start()

    print("Starting Developer Validation Console (DVC)... Press Ctrl+C to exit.\n")
    time.sleep(0.5)

    try:
        with Live(make_layout(state.get_snapshot()), refresh_per_second=8, screen=True) as live:
            while True:
                time.sleep(0.125)  # 8 FPS refresh rate
                snapshot = state.get_snapshot()
                live.update(make_layout(snapshot))
    except KeyboardInterrupt:
        print("\nDeveloper Validation Console closed cleanly.")
    except Exception as err:
        print(f"\nConsole Rendering Error: {err}")
    finally:
        global_event_bus.unsubscribe(state.on_event)


if __name__ == "__main__":
    run_console()
