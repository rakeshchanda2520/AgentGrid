"""In-process WebSocket rooms (seam: `publish`). Rooms: `conv:<id>` (widget, simulator), `tenant:<id>` (inbox).

ponytail: one process holds every socket, so the PoC runs a single Uvicorn worker. Target: Redis pub/sub.
"""

import contextlib
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

_rooms: dict[str, set[WebSocket]] = defaultdict(set)


def join(room: str, ws: WebSocket) -> None:
    _rooms[room].add(ws)


def leave(ws: WebSocket) -> None:
    for members in _rooms.values():
        members.discard(ws)


async def publish(room: str, event: dict[str, Any]) -> None:
    for ws in list(_rooms.get(room, ())):
        try:
            await ws.send_text(json.dumps(event, default=str))
        except Exception:
            with contextlib.suppress(Exception):
                _rooms[room].discard(ws)


def connected(room: str) -> int:
    return len(_rooms.get(room, ()))
