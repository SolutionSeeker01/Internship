from typing import Any, Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime

# Import store module to retrieve current snapshot
from market_data.store import get_market_data
from utils.logger import get_logger

# Set up logging
logger = get_logger(__name__)

# Initialize router
router = APIRouter()


class ConnectionManager:
    """
    Manages active WebSocket connections.
    
    Handles client registry, safe additions, clean removals, and broadcast routing.
    """
    def __init__(self) -> None:
        # Using a set for O(1) additions and removals
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts the WebSocket connection without registering for broadcasts yet."""
        await websocket.accept()

    def register(self, websocket: WebSocket) -> None:
        """Registers the accepted connection to receive broadcasts."""
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client registered. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Removes client from active registry."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Sends a JSON message to all active connections.
        Handles failures due to stale connections gracefully by removing them.
        """
        if not self.active_connections:
            return

        failed_connections: Set[WebSocket] = set()
        
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send message to websocket client: {e}")
                failed_connections.add(connection)

        # Clean up any dead connections identified during broadcast
        for connection in failed_connections:
            self.disconnect(connection)


# Global connection manager instance
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    FastAPI WebSocket endpoint.
    
    Accepts new client connections, pushes the initial snapshot from store,
    and registers the client to receive live updates afterward.
    """
    await manager.connect(websocket)
    
    # 1. Send the initial snapshot of all market data immediately
    try:
        snapshot = get_market_data()
        
        # Explicitly serialize datetime fields to ISO strings at the WebSocket boundary
        serialized_snapshot = {}
        for key, tick in snapshot.items():
            serialized_tick = dict(tick)
            ts = serialized_tick.get("timestamp")
            if isinstance(ts, datetime):
                serialized_tick["timestamp"] = ts.isoformat()
            serialized_snapshot[key] = serialized_tick

        await websocket.send_json({
            "type": "snapshot",
            "data": serialized_snapshot
        })
        logger.debug("Sent initial market data snapshot to new client.")
    except Exception as e:
        logger.error(f"Failed to send initial snapshot: {e}")
        # Safely close connection on failure
        await websocket.close()
        return

    # 2. Register for live updates only AFTER snapshot is successfully sent
    manager.register(websocket)

    # 3. Maintain loop to receive messages and monitor disconnect event
    try:
        while True:
            # We call receive_text to block and wait for user messages (if any)
            # and to automatically detect when a client terminates the connection.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Client initiated WebSocket disconnect.")
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket session: {e}")
    finally:
        manager.disconnect(websocket)


async def broadcast_market_update(data: Dict[str, Any]) -> None:
    """
    Broadcasts real-time market updates to all connected clients.
    
    This matches the expected public API invoked by ticker callbacks.
    
    Args:
        data (Dict[str, Any]): Normalized tick update data.
    """
    logger.debug("Broadcasting market update to all WebSocket clients.")
    
    # Explicitly serialize datetime timestamp to ISO string before broadcast
    serialized_data = dict(data)
    ts = serialized_data.get("timestamp")
    if isinstance(ts, datetime):
        serialized_data["timestamp"] = ts.isoformat()

    await manager.broadcast({
        "type": "update",
        "data": serialized_data
    })
