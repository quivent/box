"""Tests for the boxd cross-box scheduler (box/boxd/fleet.py).
Unit: pick() eligibility/ordering. Live: dispatch a real `demo` job to the running
boxd on :9810 and watch it complete through boxd's own /jobs queue.
   /home/ubuntu/quivent/render/box/.venv/bin/python -m pytest box/tests/test_fleet.py
   (or run directly: .venv/bin/python box/tests/test_fleet.py)
"""
import asyncio, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # box/
from boxd import fleet
import httpx

P = [0, 0]
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name); P[0 if cond else 1] += 1

# ---- unit: pick() ----
S = [
    {"name": "a", "up": True,  "role": "member",  "latency_ms": 12, "caps": {"vram_total_mb": 97871}},
    {"name": "b", "up": True,  "role": "compute", "latency_ms": 5,  "caps": {"vram_total_mb": 49152, "vram_free_mb": 40000}},
    {"name": "c", "up": False, "role": "compute", "latency_ms": 1,  "caps": {"vram_total_mb": 97871}},
    {"name": "d", "up": True,  "role": "compute", "latency_ms": 9,  "caps": {"vram_total_mb": 97871, "vram_free_mb": 90000}},
]
check("down box never picked", fleet.pick([S[2]]) is None)
check("role filter", fleet.pick(S, role="member")["name"] == "a")
check("compute: prefers most free VRAM (d over b)", fleet.pick(S, role="compute")["name"] == "d")
check("VRAM need excludes too-small box", fleet.pick(S, role="compute", need_vram_mb=60000)["name"] == "d")
check("impossible need -> none", fleet.pick(S, need_vram_mb=9_000_000) is None)
check("no boxes -> none", fleet.pick([]) is None)

# ---- live VRAM (from /telemetry) drives scheduling ----
T = [
    {"name": "x", "up": True, "role": "compute", "latency_ms": 5, "running": 0, "caps": {"vram_total_mb": 97871, "vram_free_mb": 20000}},
    {"name": "y", "up": True, "role": "compute", "latency_ms": 5, "running": 2, "caps": {"vram_total_mb": 97871, "vram_free_mb": 20000}},
    {"name": "z", "up": True, "role": "compute", "latency_ms": 5, "running": 3, "caps": {"vram_total_mb": 97871, "vram_free_mb": 80000}},
]
check("most live-free VRAM wins (even with more running)", fleet.pick(T, role="compute")["name"] == "z")
check("free-VRAM tie -> fewest running jobs", fleet.pick(T[:2], role="compute")["name"] == "x")
check("live free VRAM < need excludes (despite total ok)", fleet.pick([T[0]], need_vram_mb=50000) is None)

# ---- live: dispatch a demo job to the running boxd ----
BOXD = "http://127.0.0.1:9810"
try:
    httpx.get(BOXD + "/health", timeout=3).raise_for_status()
    live = True
except Exception as e:
    live = False
    print(f"(skipping live test — boxd not reachable: {e})")

if live:
    boxes = [{"name": "boxd-local", "origin": BOXD, "role": "member", "caps": {"vram_total_mb": 97871}}]
    st = asyncio.run(fleet.boxes_status(boxes))
    check("live: boxd-local probes UP", st and st[0]["up"] and st[0].get("boot"))
    check("live: /telemetry merged vram_free into caps", (st[0].get("caps") or {}).get("vram_free_mb") is not None)
    chosen = fleet.pick(st)
    check("live: scheduler picks the box", chosen is not None)
    job = asyncio.run(fleet.dispatch_to(chosen, "demo", {"steps": 2}))
    jid = job.get("id") or job.get("job")
    check("live: dispatched -> boxd job id", bool(jid))
    # follow the job through boxd's own queue to completion
    state = None
    for _ in range(30):
        j = httpx.get(f"{BOXD}/jobs/{jid}", timeout=3).json()
        state = j.get("state")
        if state in ("done", "error"):
            break
        time.sleep(0.3)
    check("live: job ran on the box and completed (done)", state == "done")

print(f"\n{P[0]} passed, {P[1]} failed")
raise SystemExit(1 if P[1] else 0)
