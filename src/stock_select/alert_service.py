"""WebSocket alert broadcast service.

Manages WebSocket connections and broadcasts new announcement alerts
to connected clients in real-time.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BroadcastManager:
    """Thread-safe WebSocket broadcast manager."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}  # id -> websocket
        self._lock = asyncio.Lock()

    async def register(self, ws: Any) -> str:
        """Register a WebSocket connection and return its ID."""
        client_id = id(ws)
        async with self._lock:
            self._clients[client_id] = ws
        logger.info("WebSocket client registered, total=%d", len(self._clients))
        return client_id

    async def unregister(self, ws: Any) -> None:
        """Remove a WebSocket connection."""
        client_id = id(ws)
        async with self._lock:
            self._clients.pop(client_id, None)
        logger.info("WebSocket client unregistered, total=%d", len(self._clients))

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Broadcast a JSON event to all connected clients."""
        message = json.dumps({"type": event_type, **data})
        to_remove = []
        async with self._lock:
            for cid, ws in list(self._clients.items()):
                try:
                    await ws.send_text(message)
                except Exception:
                    to_remove.append(cid)

        for cid in to_remove:
            self._clients.pop(cid, None)

        if to_remove:
            logger.warning("Removed %d dead WebSocket connections", len(to_remove))

    @property
    def client_count(self) -> int:
        return len(self._clients)
