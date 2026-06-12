from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from . import config, events, health, jobs, telemetry, upstream


@asynccontextmanager
async def lifespan(app: FastAPI):
    events.publish("boxd.started", {"name": config.BOX_NAME, "boot": config.BOOT_ID})
    yield
    events.publish("boxd.stopping", {"name": config.BOX_NAME, "boot": config.BOOT_ID})


def create_app() -> FastAPI:
    app = FastAPI(title="boxd", version=__version__, lifespan=lifespan)

    # Shared-secret gate (HTTP). No-op when TOKEN is unset (local dev). WS auth
    # is enforced in the /events handler since middleware doesn't see upgrades.
    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        if config.TOKEN and request.url.path not in config.OPEN_PATHS:
            if request.headers.get("authorization") != f"Bearer {config.TOKEN}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    # Scoped to the controller's webview origin — not "*". See config.ALLOWED_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(jobs.router)
    app.include_router(telemetry.router)
    app.include_router(upstream.router)
    return app


app = create_app()
