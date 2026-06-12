# Troubleshooting

Real failure modes, in roughly the order they bite when bringing a box onto the fleet.

## boxd is reachable from the public internet (getting scanned)

**Symptom:** `boxd.log` fills with `GET /wp-login.php`, `/cgi-bin/luci`, random `POST /` from public IPs.

**Cause:** boxd bound to `0.0.0.0`, or a reverse proxy forwards a public domain → `127.0.0.1:9810`.

**Fix:** bind the **tunnel address only** — `BOXD_HOST=10.200.0.x`. boxd should be reachable *only* over WireGuard. Set `BOXD_TOKEN` regardless. After rebinding, the registry origin must follow (see *registry/origin drift* below).

## `IndexError: 2` on import (won't start)

**Symptom:** `boxd` exits immediately; trace ends in `Path(__file__).resolve().parents[2] / ...`.

**Cause:** code that walks `parents[2]` assumes a fixed directory depth. If boxd runs from a shallower path (e.g. a bind-mount of just `box/` into a container at `/box`), `parents[2]` doesn't exist.

**Fix:** run boxd from its real depth, or mount enough of the tree that `parents[2]` resolves. The repo's `WorkingDirectory` is the box root; preserve it.

## boxd won't stay up when I start it by hand

**Symptom:** you launch `./run-dev.sh` (or `python -m boxd`) in a shell and it dies when the shell/session ends.

**Cause:** an ephemeral or sandboxed shell reaps its children on exit.

**Fix:** use the systemd **user** unit (`Restart=always`). `systemctl --user restart boxd`. For survival across logout: `loginctl enable-linger $USER`. Do not rely on `nohup`/`&` from an ephemeral shell.

## 401 on `/u/...` or `/jobs`

**Symptom:** `/health` is `200` but `/u/api/build` and `/jobs` return `{"error":"unauthorized"}` `401`.

**Cause:** the token gate is on (good). Non-`OPEN_PATHS` require `Authorization: Bearer <BOXD_TOKEN>`.

**Fix:** send the header: `curl -H "Authorization: Bearer $BOXD_TOKEN" http://10.200.0.x:9810/u/api/build`. WebSocket: `ws://…/events?token=$BOXD_TOKEN`. A `401` from an *un*authenticated probe is correct, secure behavior — not a regression.

## systemd unit stuck `activating (auto-restart)`

**Symptom:** `systemctl --user status boxd` loops; `:9810` is held by a different process.

**Cause:** a **manual** boxd is holding the port, so the unit can't bind and respins every `RestartSec`.

**Fix:** stop the manual one (`kill <pid>` / `pkill -f 'BOXD_HOST=127.0.0.1'`), then `systemctl --user restart boxd`. Pick one supervisor — the systemd unit — and let it own the port.

## Manager / fleet can't see a box that *is* up

**Symptom:** the box's boxd answers on the tunnel, but `fleet.boxes_status()` shows it down / the controller doesn't list it.

**Cause:** **registry/origin drift** — the registry (`ui/controller/boxes.json` or `FLEET_BOXES`) still points the box at a public domain (or old port) that no longer answers because boxd moved to the tunnel.

**Fix:** set the box's `origin` to its tunnel address: `http://10.200.0.x:9810`. The aggregator probes `origin/health` + `origin/telemetry`.

## Manager probes a box and gets 401

**Symptom:** registry points at the right tunnel origin, but `boxes_status` still reports the box unhealthy/unauthorized.

**Cause:** `fleet._auth()` uses a **single** `BOXD_TOKEN` (the manager's `config.TOKEN`) for *every* box. If the target box's `BOXD_TOKEN` differs, the probe is rejected.

**Fix (today):** use one **shared** `BOXD_TOKEN` across the fleet. **Tuning target:** evolve `_auth()` to per-box tokens carried in the registry (out-of-band secret, not committed) so boxes can rotate independently.

## A dispatched `proc` job never finishes / no output

**Symptom:** `/jobs/<id>` stays `running`, `log_tail` empty.

**Cause:** `payload.cmd` doesn't flush stdout line-by-line (buffered), or it's waiting on input.

**Fix:** ensure the command flushes per line (`python -u`, `PYTHONUNBUFFERED=1`, `stdbuf -oL`). `proc` streams stdout as `job.log`; a fully-buffered child looks hung until it exits.

---

## Tuning backlog (known rough edges)

- **Single shared token** → per-box tokens in the registry.
- **Public-NIC default** in older unit files → default `BOXD_HOST` to the tunnel; refuse to start off-loopback without a token.
- **Path-depth fragility** (`parents[2]`) → resolve roots from an env/anchor, not directory arithmetic.
- **Registry origin** lives in `ui/controller/boxes.json` (UI repo) while boxd lives here → consider a `FLEET_BOXES` file owned by this repo so the registry travels with the daemon.
- **Manual vs systemd** contention → ship only the systemd path; make `run-dev.sh` refuse to start if the unit is active.
