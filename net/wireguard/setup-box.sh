#!/usr/bin/env bash
# One-shot box-side bring-up: keygen + fill box.conf (manager pubkey baked in) +
# print what to run. Collapses the per-box procedure to one command so the fleet
# comes up in parallel.
#
#   ./setup-box.sh gh200-1 10.200.0.2
#   ./setup-box.sh gh200-2 10.200.0.3
#   ./setup-box.sh b200    10.200.0.4
set -euo pipefail
cd "$(dirname "$0")"

NAME="${1:?usage: setup-box.sh <name> <wg-addr>   e.g. gh200-1 10.200.0.2}"
ADDR="${2:?usage: setup-box.sh <name> <wg-addr>   e.g. gh200-1 10.200.0.2}"
MANAGER_PUB="${MANAGER_PUB:-FTq58hPJfDfcO/lboYC1iV408VkQ48W5Nho+RF2w9HA=}"
PORT="${WG_PORT:-51820}"

command -v wg >/dev/null 2>&1 || { echo "installing wireguard…"; sudo apt-get update -qq && sudo apt-get install -y wireguard; }

./gen-keys.sh "$NAME"
umask 077
cat > box.conf <<EOF
[Interface]
PrivateKey = $(cat "keys/${NAME}.key")
Address = ${ADDR}/24
ListenPort = ${PORT}

[Peer]
# manager
PublicKey = ${MANAGER_PUB}
AllowedIPs = 10.200.0.1/32
EOF

echo
echo "box.conf written for ${NAME} (${ADDR})."
echo "SEND TO MANAGER → pubkey: $(cat "keys/${NAME}.pub")   |   plus this box's public IP"
echo "THEN (root + UDP ${PORT} open inbound):"
echo "  sudo wg-quick up ./box.conf"
echo "  cd ../.. && BOXD_HOST=${ADDR} BOXD_TOKEN=\$(openssl rand -hex 24) ./run-dev.sh   # note the token, send it too"
