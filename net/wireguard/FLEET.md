# Fleet bring-up — coordination board

**Coordinator:** the Mac controller/manager session. **Substrate:** this repo —
box-agents `git pull` to get their task and commit a report file to check in.
**Secrets** (`BOXD_TOKEN`) never go in the repo; relay those via the supervision
channel.

## Topology
manager (Mac, `10.200.0.1`) dials each box over WireGuard; boxd binds the tunnel
address so `:9810` is never on the public NIC. Full procedure in `README.md`.

## Status board (coordinator maintains this table)

| slot | hardware | wg addr | boxd | tunnel | reported |
|------|----------|---------|------|--------|----------|
| manager | Mac M4 | 10.200.0.1 | n/a | ready | pubkey `FTq58hPJfDfcO/lboYC1iV408VkQ48W5Nho+RF2w9HA=` |
| gh200-1 | GH200 | 10.200.0.2 | — | — | unclaimed |
| gh200-2 | GH200 | 10.200.0.3 | — | — | unclaimed |
| b200 | B200 | 10.200.0.4 | — | — | unclaimed |

A box is already live publicly as **`render`** (boot `ac84fe3484a8`, boxd 0.1.0,
token-gated). The agent on that box: in your report file, set `"is_render": true`
so I can dedupe the registry (render = one of these three, not a fourth box).

## Box-agent protocol — one command, then one report file

```
cd <repo>/box/net/wireguard && git pull
./setup-box.sh <slot> <wg-addr>          # e.g. ./setup-box.sh gh200-1 10.200.0.2
# run the two root steps it prints (sudo wg-quick up; BOXD_HOST=<addr> … run-dev.sh)
```
Then drop **`box/net/wireguard/fleet/<slot>.json`** (separate file per box → no
merge conflicts) and commit+push it:
```json
{ "slot": "gh200-1", "pubkey": "<keys/gh200-1.pub>", "public_ip": "1.2.3.4", "boxd_up": true, "is_render": false }
```
Relay your `BOXD_TOKEN` separately (supervision channel), not in the JSON.

## Coordinator actions, per report received
1. Read `fleet/<slot>.json` → fill that peer block in `manager.conf` (pubkey + public IP).
2. `sudo wg-quick up ./manager.conf` (or reload) → `ping <addr>` → `curl http://<addr>:9810/health`.
3. Mark `boxd`/`tunnel` green in the table above, commit the board.
4. When all three GPU boxes are green, the controller shows the full fleet live.
