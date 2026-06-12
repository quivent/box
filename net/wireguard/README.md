# Raw WireGuard mesh — manager ↔ boxes

The self-owned alternative to Tailscale: WireGuard with hand-listed peers, no
coordination server, no SaaS. Fits the fleet because **boxes have public IPs**
and the **manager is behind NAT** — WireGuard's easy direction (manager dials,
box listens). Star topology: manager at the hub, one spoke per box; boxes never
talk to each other.

```
  manager (Mac)            box: b200 (public IP)
  10.200.0.1  ── WG/UDP 51820 ──▶  10.200.0.2
  (dials, NAT)                     (listens)        boxd binds 10.200.0.2:9810
```

Fleet addresses on `10.200.0.0/24`:

| host | wg addr | role |
|---|---|---|
| manager (Mac) | `10.200.0.1` | dials all boxes |
| gh200-1 | `10.200.0.2` | GPU box |
| gh200-2 | `10.200.0.3` | GPU box |
| b200 | `10.200.0.4` | GPU box |

Fast path per box (one command, then two root steps it prints):
`./setup-box.sh gh200-1 10.200.0.2`

## Why this is private without a firewall rule on :9810

boxd binds to the **WireGuard address** (`BOXD_HOST=10.200.0.2`), not `0.0.0.0`
— so `:9810` exists only inside the tunnel, never on the public NIC. The box's
sole public exposure is UDP 51820, and WireGuard **silently drops** any packet
without a valid key (no reply to scanners — the port looks closed). `BOXD_TOKEN`
is then defense-in-depth on top.

## Setup

Each host generates its own keypair; only `.pub` is shared. `wg`/`wg-quick`
needed both ends (`brew install wireguard-tools` on the Mac — note `~/bin/wg`
shadows it, so `gen-keys.sh` probes by version; `apt install wireguard` on Linux).

**1. Keys (each host, locally):**
```
./gen-keys.sh manager     # on the Mac  -> keys/manager.{key,pub}
./gen-keys.sh b200        # on the box  -> keys/b200.{key,pub}
```
Exchange the two `.pub` strings (public keys are safe to send).

**2. Configs:** copy each template to `manager.conf` / `box.conf` (gitignored)
and fill `<…>`: each host's own `PrivateKey`, the other's `PublicKey`, and the
box's public IP in the manager's `Endpoint`.

**3. Bring up (needs root — run yourself):**
```
# box:      sudo wg-quick up ./box.conf      # + open UDP 51820 inbound
# manager:  sudo wg-quick up ./manager.conf
```

**4. boxd binds to the tunnel:**
```
# on the box:
BOXD_HOST=10.200.0.2 BOXD_TOKEN=<secret> ./run-dev.sh
```

**5. Verify from the manager:**
```
ping 10.200.0.2
curl -s http://10.200.0.2:9810/health        # {name, boot, …}
```

**6. Register the box** in `ui/controller/boxes.json`:
```json
{ "name": "b200", "origin": "http://10.200.0.2:9810" }
```

## Adding a box

`gen-keys.sh <name>` on it, give it `10.200.0.3`, add one `[Peer]` block to
`manager.conf` (its pubkey, its public-IP endpoint, `AllowedIPs = 10.200.0.3/32`),
`wg-quick up` both, add a `boxes.json` entry. No other host changes.

## Persistence

`wg-quick` interfaces don't survive reboot by themselves. On the box, enable the
bundled unit: `sudo systemctl enable wg-quick@box`. On the Mac, re-run `wg-quick
up` after reboot (or a LaunchDaemon). The manager's `PersistentKeepalive = 25`
keeps the live tunnel up across NAT timeouts and laptop sleep.
