"""Proves the proc-runner streams a real subprocess and supervises it — runs
the runner in-process (no server, no GPU) against the in-repo stand-in worker.

    python3 box/tests/test_jobs.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # box/ on path

import boxd.jobs as jb
from boxd.jobs import JobRequest, create_job, cancel_job, _JOBS, _JOB_TASKS

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standin_worker.py")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


async def test_proc_streams_and_exits():
    seen = []
    orig = jb.publish
    jb.publish = lambda t, d=None: (seen.append((t, d)), orig(t, d))[1]
    try:
        job = await create_job(JobRequest(kind="proc", payload={
            "cmd": ["python3", "-u", FIXTURE, "4", "0.2"],
            "progress_re": "progress=([0-9.]+)",
        }))
        await _JOB_TASKS[job["id"]]
    finally:
        jb.publish = orig

    logs = [d["line"] for t, d in seen if t == "job.log"]
    rec = _JOBS[job["id"]]
    assert any("step 1/4" in l for l in logs), logs
    assert any("worker complete" in l for l in logs), logs
    assert rec["state"] == "done", rec["state"]
    assert rec["exit_code"] == 0, rec["exit_code"]
    assert rec["progress"] == 1.0, rec["progress"]
    print(f"streams+exits PASS: {len(logs)} log lines streamed, exit 0, progress 1.0")


async def test_cancel_kills_child():
    job = await create_job(JobRequest(kind="proc", payload={
        "cmd": ["python3", "-u", FIXTURE, "100", "1"],  # would run ~100s
    }))
    task = _JOB_TASKS[job["id"]]
    await asyncio.sleep(1.2)  # let it spawn + print at least one line
    pid = _JOBS[job["id"]]["pid"]
    assert pid and _alive(pid), f"child {pid} not running before cancel"

    await cancel_job(job["id"])
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.2)

    rec = _JOBS[job["id"]]
    assert rec["state"] == "cancelled", rec["state"]
    assert not _alive(pid), f"child {pid} STILL ALIVE after cancel — orphaned worker"
    print(f"cancel-kills-child PASS: child pid {pid} terminated, job state cancelled")


async def main():
    await test_proc_streams_and_exits()
    await test_cancel_kills_child()
    print("all proc-runner tests passed")


if __name__ == "__main__":
    asyncio.run(main())
