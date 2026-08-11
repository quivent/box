<div align="center">

```text
  _               
 | |__   _____  __
 | '_ \ / _ \ \/ /
 | |_) | (_) >  < 
 |_.__/ \___/_/\_\
```

**the box daemon (`boxd`) + fleet**
*Control plane for a fleet of GPU boxes over a WireGuard mesh*

[![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](#)

</div>

---

## ⚡ Overview

Control plane for a fleet of GPU boxes. **One `boxd` per box; one manager dials them all over a WireGuard mesh.** Each box runs jobs, narrates them over a live event stream, and fronts its local inference runtime — so an agent operating any box, or a scheduler on the manager, can **offload work to whichever box has the headroom and watch it run, in real time**.

> One agent operates each box. `boxd` is the nervous system they share.

---

## 📚 Table of Contents
- [🎯 Concepts](#-concepts)
- [📦 Quickstart](#-quickstart)
- [🏗️ Architecture](#️-architecture)
- [📖 API Reference](#-api-reference)
- [🔒 Auth & Security](#-auth--security)
- [🚢 The Fleet Scheduler](#-the-fleet-scheduler)
- [🌐 Networking (WireGuard)](#-networking-wireguard)
- [🚀 Production Deploy](#-production-deploy)

---

## 🎯 Concepts

| term | what |
|---|---|
| **box** | a machine (GH200, B200, Mac) with a GPU and a `boxd` |
| **boxd** | the per-box daemon — a FastAPI app on `:9810`, the box's API surface to the manager |
| **manager** | the coordinator; dials every box over WireGuard and runs the scheduler |
| **the mesh** | WireGuard between boxes — boxes have public IPs, **no coordination server, no SaaS** |
| **job** | a unit of work in a box's `boxd` queue (`demo`, `proc`) |
| **event** | a job-lifecycle message on `boxd`'s `/events` stream |
| **the `/u` front** | a streamed proxy to the box's legacy inference runtime (`INFERENCE_URL`, default `:8188`) |

---

## 📦 Quickstart 

> [!TIP]
> Run a single box with no GPU required!

```bash
cd box
./run-dev.sh                                   # builds .venv on first run, uvicorn on :9810
curl localhost:9810/health
curl -XPOST localhost:9810/jobs -H 'content-type: application/json' \
     -d '{"kind":"demo","payload":{}}'         # GPU-free lifecycle exercise
curl 'localhost:9810/events/recent?n=10'       # watch it narrate
```

`demo` runs the full job lifecycle with no GPU, so the contract is testable on any laptop, then the same artifact deploys to a real box and the `proc` kind spawns real work.

---

## 🏗️ Architecture

`boxd` is a FastAPI app (`boxd/main.py`) composed of small routers:

| module | surface |
|---|---|
| `health.py` | `GET /health`, `GET /api/universe/version` (compat shim — the boot-id contract the legacy vite middleware served) |
| `events.py` | `WS /events` (one multiplexed stream, ring-buffer catch-up via `?since=seq`), `GET /events/recent?n=` |
| `jobs.py` | `POST /jobs`, `GET /jobs[/<id>]` — queue + subprocess supervision (`demo`, `proc`) |
| `telemetry.py` | `GET /telemetry` — GPU/VRAM/load in the fleet aggregator's host shape |
| `upstream.py` | `* /u/{path}` — streamed HTTP front for the inference runtime (preserves SSE; no read timeout) |
| `fleet.py` | `GET /fleet/boxes`, `POST /fleet/dispatch` — the registry + scheduler (`probe`, `pick`, `dispatch_to`) |
| `config.py` | env + constants: `BOXD_HOST/PORT/TOKEN`, `INFERENCE_URL`, `OPEN_PATHS` |

### Request lifecycle — a dispatched job

```text
manager:  fleet.pick(role="compute", need_vram_mb=N)   # choose the box with the most free VRAM
   →      fleet.dispatch_to(box, kind, payload)         # POST box:/jobs  (Bearer token)
box:      boxd queues → runs                            # proc → spawn subprocess, stream stdout
   →      emits job.queued / job.started / job.progress / job.done on /events
manager:  (subscribed to box:/events) sees it live
```

**Offload→onload is native, not a new protocol:** the job runs on the target box and narrates over *that box's own* `/events`. Anyone subscribed — the manager, another agent — sees it.

---

## 📖 API Reference

> [!IMPORTANT]
> All non-open paths require `Authorization: Bearer <BOXD_TOKEN>` (WebSocket: `?token=<…>`).

| method | path | gated | notes |
|---|---|---|---|
| `GET` | `/health` | open | `{name, boot, version, uptime_s, upstream}` |
| `GET` | `/api/universe/version` | open | boot-id reload probe (compat shim) |
| `GET` | `/telemetry` | open | GPU/VRAM/util/load (best-effort) |
| `WS` | `/events?since=<seq>` | token (`?token=`) | live event stream + ring catch-up |
| `GET` | `/events/recent?n=<N>` | token | last N events |
| `POST` | `/jobs` | token | `{kind, payload}` → job record |
| `GET` | `/jobs[/<id>]` | token | ledger |
| `*` | `/u/{path}` | token | streamed proxy to `INFERENCE_URL` (e.g. `/u/api/build` → `:8188/api/build`) |
| `GET` | `/fleet/boxes` | token | live status of every registered box |
| `POST` | `/fleet/dispatch` | token | pick best-fit box + dispatch a job to it |

<details>
<summary><b>Job Record Schema</b></summary>

```json
{ "id": "4c401af819", "kind": "demo", "payload": {}, "state": "queued|running|done|error|cancelled",
  "progress": 0.0, "pid": null, "exit_code": null,
  "created_at": 0, "started_at": null, "finished_at": null, "result": null, "error": null, "log_tail": [] }
```

Job kinds: **`demo`** (fake lifecycle, GPU-free), **`proc`** (`payload.cmd` = argv/string → spawned subprocess, stdout streamed as `job.log`, supervised to exit).
</details>

---

## 🔒 Auth & Security

Shared-secret bearer gate. `config.TOKEN ← BOXD_TOKEN`. `OPEN_PATHS = {/health, /api/universe/version, /telemetry, /api/mm/host}` are ungated (liveness leaks nothing); everything else returns `401` without `Authorization: Bearer <token>`. **Unset token ⇒ fully open — local dev only.** A box reachable off-loopback MUST set a token (or gate at a reverse proxy).

### Security Model
1. **Bind the tunnel only** (`BOXD_HOST=10.200.0.x`). Never `0.0.0.0` or the public NIC — an exposed boxd gets scanned and is a remote-exec surface (`/u` + `proc`).
2. **Always set `BOXD_TOKEN`** off loopback.
3. **Never root.** The `/u` proxy and `proc` runners must run unprivileged.
4. **Secrets never in the repo.** Private keys (`net/wireguard/keys/`), filled `*.conf`, and tokens are gitignored; relay tokens out-of-band, not in the registry.

---

## 🚢 The Fleet Scheduler

`fleet.load_boxes()` reads the registry — `FLEET_BOXES` env or `ui/controller/boxes.json` — a list of `{name, origin, role?, caps?}`. Then:

- `boxes_status()` probes each box (`/health` + `/telemetry`) → liveness, free VRAM, latency.
- `pick(statuses, role, need_vram_mb)` → the **live** box with the **most free VRAM** that satisfies `role` and `need_vram_mb` (down boxes excluded; impossible needs → `None`).
- `dispatch_to(box, kind, payload)` → `POST origin/jobs` with the bearer token.

Registry origins should be the box's **tunnel** address (`http://10.200.0.x:9810`), not a public domain — `boxd` binds the tunnel only (see Security).

---

## 🌐 Networking (WireGuard)

A **manager** (`10.200.0.1`) dials each box; `boxd` binds the **tunnel** address (`10.200.0.x`) so `:9810` is never on the public NIC. Boxes have public IPs (the WG endpoint, `:51820`).

<details>
<summary><b>Bring-up — two roles</b></summary>
Full procedure in [`net/wireguard/README.md`](net/wireguard/README.md) + [`net/wireguard/FLEET.md`](net/wireguard/FLEET.md):

- **Manager:** `apt install wireguard` → `./gen-keys.sh manager` → write `manager.conf` (Address `10.200.0.1`, `ListenPort 51820`) → `sudo wg-quick up ./manager.conf`. Hand box-agents the manager **pubkey** + **endpoint** (`<public-ip>:51820`).
- **Box:** `MANAGER_PUB=<manager-pubkey> ./setup-box.sh <slot> <wg-addr>` (e.g. `b200 10.200.0.4`) → add the manager `Endpoint` + `PersistentKeepalive` if the box dials in → `sudo wg-quick up ./<slot>.conf` → run `boxd` with `BOXD_HOST=<wg-addr>` → commit `net/wireguard/fleet/<slot>.json` `{slot, pubkey, public_ip, boxd_up, is_render}`. The manager fills the peer block and reloads, then `ping <wg-addr>` / `curl <wg-addr>:9810/health`.

Slot map (default `/24`): manager `10.200.0.1`, then one address per box.
</details>

---

## 🚀 Production Deploy

Install the systemd unit ([`systemd/boxd.service`](systemd/boxd.service)) as a **user** unit (`systemctl --user enable --now boxd`) — unprivileged, because `/u` proxies traffic and `proc` jobs spawn subprocesses; **never run boxd as root**. Drop-in for the box's identity:

```ini
[Service]
Environment="BOXD_HOST=10.200.0.4"            # bind the tunnel, not 0.0.0.0
Environment="BOXD_TOKEN=<secret>"             # required off-loopback
Environment="INFERENCE_URL=http://127.0.0.1:8188"
```

`Restart=always` keeps it up across crashes and reboots (use `loginctl enable-linger` for the user so it survives logout).

### Multi-agent operation
One agent operates each box; this repo + the mesh are how they coordinate. Box-agents `git pull` to get their task and commit a report (`net/wireguard/fleet/<slot>.json`) — separate file per box, no merge conflicts. There is no central lock: **each box is authoritative for its own jobs**, and the manager aggregates the fleet by subscribing to every box's `/events`. Dispatch flows one way (manager → box `/jobs`); visibility flows the other (box `/events` → manager) — same daemon, same tunnel, symmetric.

---

## 🔧 Troubleshooting & Tests

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for the real failure modes (public exposure, path-depth import crash, systemd persistence, the 401 token gate, registry/origin drift, shared-token gotchas).

```bash
.venv/bin/python -m pytest tests        # fleet scheduler + job queue, GPU-free
```
