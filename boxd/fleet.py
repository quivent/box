"""Fleet coordination for boxd — the cross-box SCHEDULER (proposal module).

This is the layer missing between the controller (per-box up/down monitor) and each
box's `/jobs` queue: given a job, pick the best-fit box by role + capability + liveness
and dispatch it to that box's boxd `/jobs`. The job then runs there and narrates over
its own `/events` — so offload→onload is native to boxd, not a new protocol.

Design folded in from the earlier `/api/fleet/*` work (roles, scheduling, offload), now
expressed on the real boxd contract instead of bolted onto the legacy :8188 runtime.

Registry: the controller's `boxes.json`. Roles/caps are read from OPTIONAL fields on each
entry (additive — absent ⇒ role "member", eligible); when `/health` later carries
`vram_free_mb`/`role`, `pick()` uses live values automatically.

Mount on the hub box with one line in main.py:  `app.include_router(fleet.router)`
(Harmless on a leaf box — it just sees itself.) Not wired here, to avoid touching
in-flight files.
"""
from __future__ import annotations
import asyncio, json, os, time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException

TOKEN = os.environ.get("BOXD_TOKEN") or None
_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=8.0, pool=3.0)


def _registry_path() -> Optional[Path]:
    for c in (os.environ.get("FLEET_BOXES"),
              str(Path(__file__).resolve().parents[2] / "ui" / "controller" / "boxes.json")):
        if c and Path(c).exists():
            return Path(c)
    return None


def load_boxes() -> list[dict]:
    p = _registry_path()
    if not p:
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


async def probe(client: httpx.AsyncClient, box: dict) -> dict:
    """Liveness from /health; live GPU + load from /telemetry (best-effort, so older
    boxes without it still schedule on registry caps + latency)."""
    origin = box["origin"].rstrip("/")
    role = box.get("role", "member")
    caps = dict(box.get("caps", {}))
    t0 = time.time()
    health = None
    try:
        r = await client.get(origin + "/health", headers=_auth())
        if r.status_code == 200:
            health = r.json()
    except Exception:
        pass
    if health is None:
        return {**box, "up": False, "latency_ms": None, "role": role, "caps": caps, "running": None}
    latency = round((time.time() - t0) * 1000, 1)
    running = None
    gpu = None
    try:
        rt = await client.get(origin + "/telemetry", headers=_auth())
        if rt.status_code == 200:
            tele = rt.json()
            gpu = tele.get("gpu") or {}
            if gpu.get("mem_total_mb") is not None:
                caps["vram_total_mb"] = gpu["mem_total_mb"]
                if gpu.get("mem_used_mb") is not None:
                    caps["vram_free_mb"] = gpu["mem_total_mb"] - gpu["mem_used_mb"]
            if gpu.get("util_pct") is not None:
                caps["util"] = gpu["util_pct"]
            running = (tele.get("jobs") or {}).get("running")
    except Exception:
        pass
    return {**box, "up": True, "latency_ms": latency, "boot": health.get("boot"),
            "role": health.get("role", role), "caps": {**caps, **(health.get("caps") or {})},
            "running": running, "gpu": gpu}


async def boxes_status(boxes: Optional[list[dict]] = None) -> list[dict]:
    boxes = boxes if boxes is not None else load_boxes()
    if not boxes:
        return []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return list(await asyncio.gather(*[probe(client, b) for b in boxes]))


def pick(statuses: list[dict], role: Optional[str] = None, need_vram_mb: float = 0) -> Optional[dict]:
    """Eligibility: up · role match (if asked) · enough VRAM — by live `vram_free_mb`
    when /telemetry reports it, else by registry `vram_total_mb`. Ordering (least-loaded):
    most free VRAM → fewest running jobs → lowest latency."""
    elig = []
    for s in statuses:
        if not s.get("up"):
            continue
        if role and s.get("role") != role:
            continue
        caps = s.get("caps") or {}
        free = caps.get("vram_free_mb")
        if need_vram_mb:
            if free is not None:
                if float(free) < need_vram_mb:        # live free VRAM is the truth when we have it
                    continue
            elif float(caps.get("vram_total_mb", 0) or 0) < need_vram_mb:
                continue
        run = s.get("running")
        elig.append((-(float(free)) if free is not None else 0.0,
                     run if run is not None else 0,
                     s.get("latency_ms") or 1e9, s))
    if not elig:
        return None
    elig.sort(key=lambda t: (t[0], t[1], t[2]))
    return elig[0][3]


async def dispatch_to(box: dict, kind: str, payload: dict) -> dict:
    origin = box["origin"].rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(origin + "/jobs", json={"kind": kind, "payload": payload}, headers=_auth())
        r.raise_for_status()
        return r.json()


router = APIRouter()


@router.get("/fleet/boxes")
async def fleet_boxes():
    return {"boxes": await boxes_status()}


@router.post("/fleet/dispatch")
async def fleet_dispatch(body: dict = Body(...)):
    statuses = await boxes_status()
    box = pick(statuses, role=body.get("role"), need_vram_mb=float(body.get("need_vram_mb", 0) or 0))
    if not box:
        raise HTTPException(503, "no eligible box")
    job = await dispatch_to(box, body.get("kind", "demo"), body.get("payload", {}))
    return {"dispatched": True, "box": box["name"], "origin": box["origin"],
            "job": job.get("id") or job.get("job"), "job_record": job}
