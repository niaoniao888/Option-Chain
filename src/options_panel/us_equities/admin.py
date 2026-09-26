from __future__ import annotations

import argparse
import json
import secrets
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from options_panel.config import Settings
from .credential_store import CredentialError, load_credentials
from .guide_store import GuideConflictError, GuideError, GuideStore
from .refresh_policy import public_refresh_policy
from .watchlist_store import (
    WatchlistCapacityError,
    WatchlistConflictError,
    WatchlistStore,
)


def create_admin_app(*, data_dir: Path, token: str, web_dir: Path, host: str = "127.0.0.1", port: int) -> FastAPI:
    if len(token.encode("utf-8")) < 32:
        raise ValueError("管理会话令牌至少需要 32 字节")
    watchlist = WatchlistStore(Path(data_dir) / "watchlist.json")
    guide = GuideStore(Path(data_dir) / "options-guide.json")
    app = FastAPI(title="US Options Local Admin", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_token = token
    app.state.data_dir = Path(data_dir)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def error(message: str, status: int) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})

    def authorized(request: Request) -> bool:
        scheme, _, value = request.headers.get("Authorization", "").partition(" ")
        return scheme.lower() == "bearer" and bool(value) and secrets.compare_digest(value, token)

    def write_authorized(request: Request) -> bool:
        host_header = request.headers.get("Host", "").lower()
        origin = request.headers.get("Origin", "").lower()
        client_host = request.client.host if request.client else ""
        return (
            client_host in {"127.0.0.1", "::1", "testclient"}
            and host_header in allowed_hosts
            and origin == f"http://{host_header}"
            and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json"
        )

    async def read_json_limited(request: Request, maximum: int) -> Any:
        raw_length = request.headers.get("Content-Length")
        if raw_length is not None and (not raw_length.isdigit() or int(raw_length) > maximum):
            raise ValueError("请求体大小无效")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > maximum:
                raise ValueError("请求体大小无效")
            chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体不是有效 JSON") from exc

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/") and not authorized(request):
            return error("管理会话授权失败", 401)
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD"} and not write_authorized(request):
            return error("写操作同源校验失败", 403)
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        return response

    def static(name: str):
        target = Path(web_dir) / "us-equities" / name
        return FileResponse(target) if target.is_file() else error("静态资源不存在", 404)

    @app.get("/")
    def root(): return static("admin.html")

    @app.get("/{name}")
    def asset(name: str):
        return static(name) if name in {"admin.html", "admin.js", "admin.css"} else error("静态资源不存在", 404)

    @app.get("/api/health")
    def health():
        config_error = None
        config_error_type = None
        try:
            configured = load_credentials() is not None
        except CredentialError as exc:
            configured = False
            config_error = "数据源配置无效，请检查本机管理配置"
            config_error_type = type(exc).__name__
        body: dict[str, Any] = {
            "app": "us-options-dashboard-admin",
            "status": "configured" if configured else ("configuration_error" if config_error else "configuration_required"),
            "source": "Alpaca",
            "configured": configured,
            "writable": True,
            "refresh_policy": public_refresh_policy(),
        }
        if config_error:
            body["configuration_error"] = config_error
            body["configuration_error_type"] = config_error_type
        return JSONResponse(body)

    @app.get("/api/watchlist")
    def get_watchlist():
        try:
            return JSONResponse(watchlist.get())
        except ValueError as exc:
            return error(str(exc), 503)

    @app.post("/api/watchlist")
    async def add_watchlist(request: Request):
        try:
            payload = await read_json_limited(request, 4096)
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return JSONResponse(watchlist.add_document(payload.get("symbol"), request.headers.get("If-Match", "")))
        except WatchlistConflictError as exc:
            return error(str(exc), 409)
        except WatchlistCapacityError as exc:
            return error(str(exc), 429)
        except (ValueError, UnicodeError) as exc:
            return error(str(exc), 400)

    @app.delete("/api/watchlist/{symbol}")
    def remove_watchlist(symbol: str, request: Request):
        try:
            return JSONResponse(watchlist.remove_document(symbol, request.headers.get("If-Match", "")))
        except WatchlistConflictError as exc:
            return error(str(exc), 409)
        except ValueError as exc:
            return error(str(exc), 400)

    @app.get("/api/options-guide")
    def get_guide():
        try:
            return JSONResponse(guide.get())
        except GuideError as exc:
            return error(str(exc), 503)

    @app.put("/api/options-guide")
    async def put_guide(request: Request):
        try:
            payload = await read_json_limited(request, 128 * 1024)
            if not isinstance(payload, dict) or set(payload) != {"sections"}:
                raise GuideError("请求体必须仅包含 sections")
            return JSONResponse(guide.update(payload["sections"], request.headers.get("If-Match", "")))
        except GuideConflictError as exc:
            return error(str(exc), 409)
        except GuideError as exc:
            return error(str(exc), 400)
        except (ValueError, UnicodeError) as exc:
            return error(str(exc), 400)

    return app


def _available_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="US equity options local administration")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--web-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    data_dir = args.data_dir or settings.us_data_dir
    web_dir = args.web_dir or settings.web_dir
    port = args.port or _available_port(args.host)
    if not 1 <= port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间")
    token = secrets.token_urlsafe(48)
    app = create_admin_app(data_dir=data_dir, token=token, web_dir=web_dir, host=args.host, port=port)
    if not args.no_browser:
        app.add_event_handler(
            "startup",
            lambda: threading.Timer(0.25, webbrowser.open, args=(f"http://{args.host}:{port}/#token={token}",)).start(),
        )
    uvicorn.run(app, host=args.host, port=port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
