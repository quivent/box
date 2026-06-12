import sys
import time

from fastapi import APIRouter

from . import __version__
from . import config

router = APIRouter()


@router.get("/health")
def health():
    return {
        "name": config.BOX_NAME,
        "boot": config.BOOT_ID,
        "version": __version__,
        "uptime_s": round(time.time() - config.STARTED_AT, 1),
        "python": sys.version.split()[0],
        "upstream": config.INFERENCE_UPSTREAM,
    }


# Compat shim: the swap endpoint. The controller and the dev-reload probe both
# poll /api/universe/version for a boot id today, so the daemon answers it
# identically — boxes can move from vite-middleware to boxd with zero client
# changes. Remove once every client speaks /health.
@router.get("/api/universe/version")
def version_compat():
    return {"boot": config.BOOT_ID}
