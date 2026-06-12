"""What this box is, what it's running, what it's doing.

GET /telemetry — GPU (name/util/mem/temp/power via nvidia-smi), the compute
processes on the GPU, and a job summary. The controller polls this to fill the
monitor: identity + live load + activity, per box.
"""

import shutil
import subprocess

from fastapi import APIRouter

from . import config
from .jobs import _JOBS

router = APIRouter()


def _num(s: str):
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def _smi(query: str, mode: str = "--query-gpu"):
    if not shutil.which("nvidia-smi"):
        return None
    try:
        r = subprocess.run(
            ["nvidia-smi", f"{mode}={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        return [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
    except Exception:
        return None


@router.get("/telemetry")
def telemetry():
    gpu = None
    rows = _smi("name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw")
    if rows:
        f = [x.strip() for x in rows[0].split(",")]
        if len(f) >= 4:
            gpu = {
                "name": f[0],
                "util_pct": _num(f[1]),
                "mem_used_mb": _num(f[2]),
                "mem_total_mb": _num(f[3]),
                "temp_c": _num(f[4]) if len(f) > 4 else None,
                "power_w": _num(f[5]) if len(f) > 5 else None,
            }

    procs = []
    apps = _smi("pid,process_name,used_memory", mode="--query-compute-apps")
    if apps:
        for a in apps:
            f = [x.strip() for x in a.split(",")]
            if len(f) >= 2:
                procs.append({"pid": _num(f[0]), "name": f[1], "mem_mb": _num(f[2]) if len(f) > 2 else None})

    jobs = list(_JOBS.values())
    job_summary = {
        "running": sum(1 for j in jobs if j["state"] == "running"),
        "queued": sum(1 for j in jobs if j["state"] == "queued"),
        "done": sum(1 for j in jobs if j["state"] == "done"),
        "recent": [
            {"kind": j["kind"], "state": j["state"], "progress": j["progress"]}
            for j in sorted(jobs, key=lambda j: j["created_at"], reverse=True)[:5]
        ],
    }

    return {
        "name": config.BOX_NAME,
        "boot": config.BOOT_ID,
        "gpu": gpu,
        "gpu_procs": procs,
        "jobs": job_summary,
    }


@router.get("/api/mm/host")
def mm_host():
    """Compat shim: boxd telemetry in the fleet aggregator's host shape, so the
    unified comfort-ui Fleet tab (motion/sections/fleet.tsx → /api/mm/fleet →
    each box's /api/mm/host) monitors a boxd box with NO frontend change. Same
    pattern as the /api/universe/version shim. Torch-free, so even a box without
    a working inference runtime (e.g. the B200) still reports for monitoring.
    """
    t = telemetry()
    g = t["gpu"]
    gpus = []
    if g:
        gpus.append({
            "name": g["name"],
            "util": g["util_pct"],
            "util_inst": g["util_pct"],
            "mem_used": g["mem_used_mb"],
            "mem_total": g["mem_total_mb"],
            "temp": g["temp_c"],
            "power": g["power_w"],
        })
    loaded = [
        {"id": p["name"], "state": "running", "vram": (p.get("mem_mb") or 0) * 1024 * 1024}
        for p in t["gpu_procs"]
    ]
    return {
        "hostname": config.BOX_NAME,
        "gpus": gpus,
        "trainer_running": t["jobs"]["running"] > 0,
        "runs": [],
        "loaded": loaded,
    }
