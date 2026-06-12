#!/usr/bin/env bash
# Generate a WireGuard keypair for THIS host into keys/ (gitignored).
# Each host generates its own keypair locally; only the .pub is ever shared.
# Usage: ./gen-keys.sh <name>     e.g. ./gen-keys.sh manager   |   ./gen-keys.sh b200
set -euo pipefail
cd "$(dirname "$0")"

# Find the real wg. On the Mac, ~/bin/wg is an unrelated tool that shadows it,
# so probe by version string rather than trusting PATH order.
WG="${WG:-}"
if [ -z "$WG" ]; then
  for c in wg /opt/homebrew/bin/wg /usr/bin/wg /usr/local/bin/wg; do
    if "$c" --version 2>/dev/null | grep -qi wireguard-tools; then WG="$c"; break; fi
  done
fi
[ -n "$WG" ] || { echo "wireguard-tools not found (brew/apt install wireguard-tools)"; exit 1; }

name="${1:-host}"
mkdir -p keys
umask 077
"$WG" genkey > "keys/${name}.key"
"$WG" pubkey < "keys/${name}.key" > "keys/${name}.pub"
echo "wrote keys/${name}.key  (PRIVATE — never share, never commit)"
echo "public key to share:    $(cat "keys/${name}.pub")"
