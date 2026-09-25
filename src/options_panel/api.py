from __future__ import annotations

import json
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from options_panel.config import APP_VERSION, Settings
from options_panel.content.guide_store import GuideError, GuideStore
from options_panel.logging import configure_logging, log_event
from options_panel.modules.bitcoin import BitcoinModule
from options_panel.modules.registry import public_modules
from options_panel.runtime.refresher import ProcessLock, Refresher
from options_panel.runtime.snapshot import DashboardState
from options_panel.us_equities.guide_store import GuideError as UsGuideError
from options_panel.us_equities.runtime import UsEquitiesRuntime
from options_panel.us_equities.watchlist_store import normalize_symbol

_HELD_COLLECTOR_LOCKS: list[ProcessLock] = []

class SnapshotResponseCache:
    def __init__(self, state: DashboardState, ttl: float = 1.0):
        self.state, self.ttl = state, ttl
        self._lock = threading.Lock()
        self._expires = 0.0
        self._body = b""

    def body(self) -> bytes:
        now = time.monotonic()
        with self._lock:
            if now >= self._expires:
                self._body = json.dumps(self.state.snapshot(), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self._expires = now + self.ttl
            return self._body


def create_app(settings: Settings | None = None, state: DashboardState | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    base = settings.base_path
    dashboard = state or DashboardState()
    guide = GuideStore(settings.data_dir / "options-guide.json")
    module = BitcoinModule(dashboard, guide)
    us_runtime = UsEquitiesRuntime(
        settings.us_data_dir,
        collector_enabled=settings.collector_enabled and settings.us_collector_enabled,
    )
    snapshot_cache = SnapshotResponseCache(dashboard)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_dir)
        app.state.bitcoin = module
        app.state.settings = settings
        app.state.us_equities = us_runtime
        lock = None
        refresher = None
        if settings.collector_enabled and settings.bitcoin_collector_enabled:
            lock = ProcessLock(settings.runtime_dir / "collector.lock")
            lock.acquire()
            refresher = Refresher(dashboard)
            refresher.start()
        us_runtime.start()
        try:
            yield
        finally:
            us_runtime.stop()
            if refresher is not None:
                refresher.stop_event.set()
                refresher.join(timeout=15)
            if lock is not None:
                if refresher is not None and refresher.is_alive():
                    # Keep the OS lock reachable until process exit. Releasing it here
                    # could allow a second collector while the first is still in I/O.
                    _HELD_COLLECTOR_LOCKS.append(lock)
                else:
                    lock.release()

    app = FastAPI(title="Options Panel", version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception):
        log_event(40, "request_failed", exception_type=type(exc).__name__)
        return JSONResponse({"error": "服务内部错误"}, status_code=500)

    @app.middleware("http")
    async def public_read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse({"error": "公开服务只允许读取"}, status_code=405, headers={"Allow": "GET, HEAD, OPTIONS"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'self'")
        return response

    def p(path: str) -> str:
        return (base + path) or "/"

    @app.get(p("/"))
    def landing():
        return file(settings.web_dir / "hub" / "index.html")

    @app.get(p("/hub/{name}"))
    def hub_asset(name: str):
        return file(settings.web_dir / "hub" / name) if name in {"hub.js", "hub.css"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    def file(path: Path):
        if not path.is_file():
            return JSONResponse({"error": "静态资源不存在"}, status_code=404)
        return FileResponse(path)

    @app.get(p("/bitcoin/desktop"))
    def desktop_redirect(): return RedirectResponse(p("/bitcoin/desktop/"), status_code=308)

    @app.get(p("/bitcoin/desktop/"))
    def desktop(): return file(settings.web_dir / "desktop" / "index.html")

    @app.get(p("/bitcoin/mobile"))
    def mobile_redirect(): return RedirectResponse(p("/bitcoin/mobile/"), status_code=308)

    @app.get(p("/bitcoin/mobile/"))
    def mobile(): return file(settings.web_dir / "mobile" / "index.html")

    @app.get(p("/bitcoin/desktop/{name}"))
    def desktop_asset(name: str):
        return file(settings.web_dir / "desktop" / name) if name in {"app.js", "style.css"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    @app.get(p("/bitcoin/mobile/{name}"))
    def mobile_asset(name: str):
        return file(settings.web_dir / "mobile" / name) if name in {"mobile.js", "mobile.css"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    @app.get(p("/bitcoin/shared/{name}"))
    def shared_asset(name: str):
        return file(settings.web_dir / "shared" / name) if name in {"guide.js", "guide.css", "period-return.js", "period-return.css"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    @app.get(p("/us-equities/desktop"))
    def us_desktop_redirect(): return RedirectResponse(p("/us-equities/desktop/"), status_code=308)

    @app.get(p("/us-equities/mobile"))
    def us_mobile_redirect(): return RedirectResponse(p("/us-equities/mobile/"), status_code=308)

    @app.get(p("/us-equities/desktop/"))
    @app.get(p("/us-equities/mobile/"))
    def us_page(): return file(settings.web_dir / "us-equities" / "index.html")

    @app.get(p("/us-equities/desktop/{name}"))
    @app.get(p("/us-equities/mobile/{name}"))
    def us_asset(name: str):
        return file(settings.web_dir / "us-equities" / name) if name in {"app.js", "style.css", "guide.js"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    @app.get(p("/api/v1/modules"))
    def modules(): return public_modules(base)

    def snapshot_response():
        return Response(snapshot_cache.body(), media_type="application/json", headers={"Cache-Control": "public, max-age=1"})

    @app.get(p("/api/v1/bitcoin/snapshot"))
    @app.get(p("/api/snapshot"))
    def snapshot(): return snapshot_response()

    @app.get(p("/api/v1/bitcoin/health"))
    @app.get(p("/api/health"))
    def health(): return JSONResponse(dashboard.health(), headers={"Cache-Control": "no-store"})

    @app.get(p("/api/v1/bitcoin/options-guide"))
    @app.get(p("/api/options-guide"))
    def options_guide():
        try: return JSONResponse(guide.get(), headers={"Cache-Control": "no-store"})
        except GuideError as exc: return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/health"))
    def us_health():
        return JSONResponse(us_runtime.health(), headers={"Cache-Control": "no-store"})

    @app.get(p("/api/v1/us-equities/watchlist"))
    def us_watchlist():
        try:
            return JSONResponse(us_runtime.watchlist.get(), headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/options-guide"))
    def us_options_guide():
        try:
            return JSONResponse(us_runtime.guide.get(), headers={"Cache-Control": "no-store"})
        except UsGuideError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/snapshot"))
    def us_snapshot(request: Request):
        query = request.query_params
        values = query.getlist("symbol")
        if len(values) != 1:
            return JSONResponse({"error": "必须指定唯一 symbol"}, status_code=400)
        try:
            symbol = normalize_symbol(values[0])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            if symbol not in us_runtime.watchlist.list():
                return JSONResponse({"error": "symbol 不在自选列表"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        versions = query.getlist("if_version")
        if len(versions) > 1 or (versions and (not versions[0] or len(versions[0]) > 96)):
            return JSONResponse({"error": "if_version 无效"}, status_code=400)
        clients, active_values = query.getlist("client_id"), query.getlist("active")
        if len(clients) > 1 or (clients and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", clients[0])):
            return JSONResponse({"error": "client_id 无效"}, status_code=400)
        if len(active_values) > 1 or (active_values and active_values[0] not in {"0", "1"}):
            return JSONResponse({"error": "active 无效"}, status_code=400)
        sequences = query.getlist("activity_seq")
        if (active_values or sequences) and not clients:
            return JSONResponse({"error": "active/activity_seq 必须与 client_id 同时使用"}, status_code=400)
        if len(sequences) > 1 or (sequences and (
                not re.fullmatch(r"\d{1,16}", sequences[0]) or int(sequences[0]) > 9007199254740991)):
            return JSONResponse({"error": "activity_seq 无效"}, status_code=400)
        active = active_values[0] == "1" if active_values else None
        return JSONResponse(us_runtime.market.snapshot(
            symbol,
            if_version=versions[0] if versions else None,
            client_id=clients[0] if clients else None,
            active=active,
            activity_seq=int(sequences[0]) if sequences else None,
        ), headers={"Cache-Control": "no-store"})

    @app.get(p("/healthz"))
    def healthz(): return {"status": "alive", "version": APP_VERSION}

    @app.get(p("/readyz"))
    def readyz():
        health_value = dashboard.health()
        ready = health_value["status"] in {"healthy", "degraded"} and not health_value["stale"] and dashboard.market_fetched_at is not None and dashboard.catalog_fetched_at is not None
        return JSONResponse({"status": "ready" if ready else "not_ready", "bitcoin": health_value}, status_code=200 if ready else 503)

    return app
