from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from options_panel.assembly import Platform
from options_panel.config import APP_VERSION


def install_system_routes(app: FastAPI, platform: Platform) -> None:
    base = platform.settings.base_path
    p = lambda path: (base + path) or "/"

    @app.get(p("/api/v1/modules"))
    def modules(): return platform.public_modules()

    @app.get(p("/api/v1/status"))
    def status():
        return JSONResponse({"status": "running", "version": APP_VERSION, "markets": platform.lifecycle.status()}, headers={"Cache-Control": "no-store"})

    @app.get(p("/healthz"))
    def healthz(): return {"status": "alive", "version": APP_VERSION}

    @app.get(p("/readyz"))
    def readyz():
        health_value = platform.bitcoin_state.health()
        ready = health_value["status"] in {"healthy", "degraded"} and not health_value["stale"] and platform.bitcoin_state.market_fetched_at is not None and platform.bitcoin_state.catalog_fetched_at is not None
        return JSONResponse({"status": "ready" if ready else "not_ready", "bitcoin": health_value}, status_code=200 if ready else 503)
