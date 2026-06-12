"""Front for the legacy inference runtime (:8188).

CONTRACT-INVENTORY.md verdict: that upstream is load-bearing — 16 anime
designs, Motion /api/mm/*, Metal, and all three SSE endpoints live there. So
the daemon fronts it at /u/* rather than deleting it; surfaces migrate off it
endpoint by endpoint.

Streamed passthrough: the body is relayed chunk-by-chunk via httpx's streaming
API, so Server-Sent Events (/api/render/inmotion-stream, generations-sse) keep
their incremental semantics instead of being buffered until the stream closes.
No read timeout — an SSE stream is meant to stay open. The /ws WebSocket proxy
stays on the vite middleware until boxd grows one (TODO).
"""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from . import config

router = APIRouter()

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

# Connect can be slow-ish; reads must never time out (SSE stays open by design).
_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


@router.api_route("/u/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def forward(path: str, request: Request):
    url = f"{config.INFERENCE_UPSTREAM}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()

    client = httpx.AsyncClient(timeout=_TIMEOUT)
    req = client.build_request(
        request.method, url, params=request.query_params, headers=headers, content=body
    )
    try:
        upstream = await client.send(req, stream=True)
    except httpx.TransportError as e:
        await client.aclose()
        return StreamingResponse(
            iter([
                f'{{"error":"upstream_unreachable","upstream":"{config.INFERENCE_UPSTREAM}","detail":"{type(e).__name__}"}}'.encode()
            ]),
            status_code=502,
            media_type="application/json",
        )

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=upstream.headers.get("content-type"),
    )
