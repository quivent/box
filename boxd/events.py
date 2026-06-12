"""One multiplexed event stream per box.

Everything the daemon does is narrated here: job lifecycle, worker state,
upstream health. The controller subscribes once per box and fans events into
its UI. A ring buffer lets late subscribers catch up (?since=seq) instead of
starting blind.

Loss is made visible, never silent: a live consumer that falls behind the
512-deep send queue, or a reconnect whose ?since= predates the 256-event ring,
gets a `gap` event telling it to resync — better a flagged discontinuity than
a hole the consumer never learns about.
"""

import asyncio
import collections
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config

router = APIRouter()

_RING_MAX = 256
_RING: collections.deque = collections.deque(maxlen=_RING_MAX)
_SUBSCRIBERS: set[asyncio.Queue] = set()
_SEQ = 0


def _gap(detail: str) -> dict:
    return {"seq": _SEQ, "ts": round(time.time(), 3), "type": "gap",
            "data": {"detail": detail, "head": _SEQ}}


def publish(type_: str, data: dict[str, Any] | None = None) -> dict:
    global _SEQ
    _SEQ += 1
    event = {"seq": _SEQ, "ts": round(time.time(), 3), "type": type_, "data": data or {}}
    _RING.append(event)
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Consumer fell behind: drop its backlog and hand it a gap marker so
            # it resyncs via ?since=. A visible gap beats silent loss.
            try:
                while True:
                    q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(_gap("subscriber overflow; reconnect with ?since=<last seq seen>"))
            except asyncio.QueueFull:
                pass
    return event


@router.get("/events/recent")
def recent(n: int = 50):
    if n <= 0:
        return {"events": [], "seq": _SEQ}
    return {"events": list(_RING)[-n:], "seq": _SEQ}


@router.websocket("/events")
async def events_ws(ws: WebSocket, since: int = 0, token: str | None = None):
    if config.TOKEN and token != config.TOKEN:
        await ws.close(code=4401)  # policy violation: unauthorized
        return
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=512)
    # Subscribe, then snapshot the ring — both synchronous, no await between, so
    # no event can interleave and be both replayed and queued (no dupes/losses).
    _SUBSCRIBERS.add(q)
    ring = list(_RING)
    try:
        # If the caller wants history older than the ring still holds, say so.
        if since and ring and since < ring[0]["seq"] - 1:
            await ws.send_json(_gap(f"requested since={since} predates buffer; oldest={ring[0]['seq']}"))
        for ev in ring:
            if ev["seq"] > since:
                await ws.send_json(ev)
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        _SUBSCRIBERS.discard(q)
