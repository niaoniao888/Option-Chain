from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from options_panel.assembly import assemble_platform
from options_panel.config import APP_VERSION, Settings
from options_panel.logging import configure_logging, log_event
from options_panel.modules.registry import MarketRegistry
from options_panel.routes import install_market_routes, install_static_routes, install_system_routes
from options_panel.runtime.snapshot import DashboardState
from options_panel.providers.registry import ProviderRegistry


def create_application(settings: Settings, state: DashboardState | None = None,
                       registry: MarketRegistry | None = None,
                       provider_registry: ProviderRegistry | None = None) -> FastAPI:
    platform = assemble_platform(settings, state, registry, provider_registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_dir)
        app.state.platform = platform
        bitcoin = platform.runtime("bitcoin")
        app.state.bitcoin = getattr(bitcoin, "module", bitcoin)
        app.state.settings = settings
        app.state.us_equities = platform.runtime("us-equities")
        platform.lifecycle.start_all()
        try:
            yield
        finally:
            platform.lifecycle.stop_all()

    app = FastAPI(title="Options Panel", version=APP_VERSION, docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception):
        log_event(40, "request_failed", exception_type=type(exc).__name__)
        return JSONResponse({"error": "服务内部错误"}, status_code=500)

    @app.middleware("http")
    async def public_read_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse({"error": "公开服务只允许读取"}, status_code=405,
                                headers={"Allow": "GET, HEAD, OPTIONS"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'self'")
        return response

    install_static_routes(app, platform)
    install_market_routes(app, platform)
    install_system_routes(app, platform)
    return app
