"""Job queue + subprocess supervision.

This is the shape the python-spawning middleware routes migrate into
(wan_load.py at devServer.ts:2835, moments_flux.py at :1317, ffmpeg, the
render CLI — 17 process-spawning routes per CONTRACT-INVENTORY.md). A job is
created over HTTP, runs as a supervised asyncio task, and narrates every
transition on the event stream.

Two runners:
- `demo` — GPU-free lifecycle exerciser (queued→running→progress→done).
- `proc` — spawns a real subprocess, streams its stdout line-by-line as
  `job.log` events, parses progress from a caller-supplied regex, captures the
  exit code, and on cancel terminates (then kills) the child so no worker is
  orphaned. A named worker (e.g. moments_flux.py) becomes a thin `_RUNNERS`
  entry that calls this with a fixed argv.
"""

import asyncio
import re
import shlex
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .events import publish

router = APIRouter()

_JOBS: dict[str, dict[str, Any]] = {}
# job id -> its supervising task, so a job can be cancelled by id (and so the
# task isn't GC'd mid-flight — asyncio only weakly references scheduled tasks).
_JOB_TASKS: dict[str, asyncio.Task] = {}

_LOG_TAIL_MAX = 50


class JobRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = {}


def _emit(job: dict, type_: str):
    publish(type_, {"job": job["id"], "kind": job["kind"], "state": job["state"],
                    "progress": job["progress"]})


async def _run_demo(job: dict):
    job["state"] = "running"
    job["started_at"] = time.time()
    _emit(job, "job.started")
    steps = int(job["payload"].get("steps", 5))
    for i in range(steps):
        await asyncio.sleep(0.4)
        job["progress"] = round((i + 1) / steps, 2)
        _emit(job, "job.progress")
    job["state"] = "done"
    job["finished_at"] = time.time()
    job["result"] = {"echo": job["payload"], "steps": steps}
    _emit(job, "job.done")


async def _run_proc(job: dict):
    """Spawn payload.cmd, stream stdout as job.log, supervise to completion."""
    cmd = job["payload"].get("cmd")
    if not cmd:
        raise ValueError("proc job requires payload.cmd (argv list or string)")
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    rx = job["payload"].get("progress_re")
    rx = re.compile(rx) if rx else None

    job["state"] = "running"
    job["started_at"] = time.time()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    job["pid"] = proc.pid
    _emit(job, "job.started")
    tail: list[str] = job.setdefault("log_tail", [])

    try:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip("\n")
            tail.append(line)
            if len(tail) > _LOG_TAIL_MAX:
                del tail[0]
            if rx:
                m = rx.search(line)
                if m:
                    try:
                        job["progress"] = round(float(m.group(1)), 4)
                    except (ValueError, IndexError):
                        pass
            publish("job.log", {"job": job["id"], "line": line, "progress": job["progress"]})
        rc = await proc.wait()
        job["exit_code"] = rc
        job["finished_at"] = time.time()
        if rc == 0:
            job["state"] = "done"
            _emit(job, "job.done")
        else:
            job["state"] = "error"
            job["error"] = f"exit {rc}"
            _emit(job, "job.error")
    except asyncio.CancelledError:
        # Supervision contract: a cancelled job must not leave its worker alive.
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
        job["exit_code"] = proc.returncode
        raise  # _run emits job.cancelled


_RUNNERS = {"demo": _run_demo, "proc": _run_proc}


async def _run(job: dict):
    runner = _RUNNERS.get(job["kind"])
    if runner is None:
        job["state"] = "error"
        job["error"] = f"unknown kind: {job['kind']}"
        job["finished_at"] = time.time()
        _emit(job, "job.error")
        return
    try:
        await runner(job)
    except asyncio.CancelledError:
        # Daemon shutdown or explicit cancel: emit a terminal event so a client
        # watching /events isn't left hanging, then honor the cancellation.
        job["state"] = "cancelled"
        job["finished_at"] = time.time()
        _emit(job, "job.cancelled")
        raise
    except Exception as e:  # noqa: BLE001 — job errors must land in the ledger, never crash the daemon
        job["state"] = "error"
        job["error"] = repr(e)
        job["finished_at"] = time.time()
        _emit(job, "job.error")


@router.post("/jobs", status_code=201)
async def create_job(req: JobRequest):
    job: dict[str, Any] = {
        "id": uuid.uuid4().hex[:10],
        "kind": req.kind,
        "payload": req.payload,
        "state": "queued",
        "progress": 0.0,
        "pid": None,
        "exit_code": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    _JOBS[job["id"]] = job
    _emit(job, "job.queued")
    task = asyncio.get_running_loop().create_task(_run(job))
    _JOB_TASKS[job["id"]] = task
    task.add_done_callback(lambda _t, jid=job["id"]: _JOB_TASKS.pop(jid, None))
    return job


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    task = _JOB_TASKS.get(job_id)
    if task is None or task.done():
        return {"id": job_id, "state": job["state"], "cancelled": False, "reason": "not running"}
    task.cancel()
    return {"id": job_id, "state": "cancelling", "cancelled": True}


@router.get("/jobs")
def list_jobs(state: str | None = None):
    jobs = list(_JOBS.values())
    if state:
        jobs = [j for j in jobs if j["state"] == state]
    return {"jobs": sorted(jobs, key=lambda j: j["created_at"], reverse=True)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return job
