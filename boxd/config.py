import os
import socket
import time
import uuid

# Identity. The boot id changes every process start — the controller detects
# box restarts by watching it (same contract the vite middleware's DEV_BOOT
# provides today).
BOOT_ID = uuid.uuid4().hex[:12]
STARTED_AT = time.time()
BOX_NAME = os.environ.get("BOX_NAME", socket.gethostname().split(".")[0])

PORT = int(os.environ.get("BOXD_PORT", "9810"))
HOST = os.environ.get("BOXD_HOST", "127.0.0.1")

# The legacy inference runtime this daemon fronts (load-bearing per
# CONTRACT-INVENTORY.md — 16 anime designs, Motion /api/mm/*, Metal, all SSE).
INFERENCE_UPSTREAM = os.environ.get("INFERENCE_URL", "http://127.0.0.1:8188")

# Shared-secret gate. When set, every surface except liveness requires
# `Authorization: Bearer <token>` (WS: `?token=`). Unset → open (local dev).
# A box exposed through Caddy MUST set this (or have Caddy enforce it): a
# 127.0.0.1 bind does not stop the operator's own browser from driving :9810.
TOKEN = os.environ.get("BOXD_TOKEN") or None

# Browsers that may call the daemon. The controller webview is not same-origin
# with any box, so the daemon is the one that must allow it. NOT "*": with
# credentials/private-network that turns every visited page into a client.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "BOXD_ALLOWED_ORIGINS",
        "tauri://localhost,https://tauri.localhost,http://localhost:9733,http://127.0.0.1:9733",
    ).split(",")
    if o.strip()
]

# Liveness is unauthenticated so the controller can detect a box pre-auth; a
# boot id leaks nothing. Everything else is gated when TOKEN is set.
OPEN_PATHS = {"/health", "/api/universe/version", "/telemetry", "/api/mm/host"}
