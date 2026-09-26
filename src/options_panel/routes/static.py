from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from options_panel.assembly import Platform


def install_static_routes(app: FastAPI, platform: Platform) -> None:
    settings, base = platform.settings, platform.settings.base_path
    p = lambda path: (base + path) or "/"

    def file(path: Path):
        if not path.is_file():
            return JSONResponse({"error": "静态资源不存在"}, status_code=404)
        return FileResponse(path)

    @app.get(p("/"))
    def landing(): return file(settings.web_dir / "hub" / "index.html")

    @app.get(p("/hub/{name}"))
    def hub_asset(name: str):
        return file(settings.web_dir / "hub" / name) if name in {"hub.js", "hub.css"} else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    def page_handler(directory: str, index_name: str):
        def handler(): return file(settings.web_dir / directory / index_name)
        return handler

    def redirect_handler(target: str):
        def handler(): return RedirectResponse(p(target), status_code=308)
        return handler

    def asset_handler(directory: str, allowed: tuple[str, ...]):
        def handler(name: str):
            return (file(settings.web_dir / directory / name) if name in allowed
                    else JSONResponse({"error": "静态资源不存在"}, status_code=404))
        return handler

    for registration in platform.registry.registrations():
        descriptor, page = registration.descriptor, registration.static_page
        for surface, route, directory, assets in (
            ("desktop", descriptor.desktop_path, page.desktop_dir, page.desktop_assets),
            ("mobile", descriptor.mobile_path, page.mobile_dir, page.mobile_assets),
        ):
            route = route if route.endswith("/") else route + "/"
            endpoint = f"{descriptor.market_id}_{surface}"
            app.add_api_route(p(route.rstrip("/")), redirect_handler(route), methods=["GET"],
                              name=endpoint + "_redirect")
            app.add_api_route(p(route), page_handler(directory, page.index_name), methods=["GET"], name=endpoint)
            app.add_api_route(p(route + "{name}"), asset_handler(directory, assets), methods=["GET"],
                              name=endpoint + "_asset")

    @app.get(p("/bitcoin/shared/{name}"))
    def shared_asset(name: str):
        allowed = {"guide.js", "guide.css", "period-return.js", "period-return.css", "market-shell.css"}
        return file(settings.web_dir / "shared" / name) if name in allowed else JSONResponse({"error": "静态资源不存在"}, status_code=404)

    @app.get(p("/shared/{name}"))
    def global_shared_asset(name: str):
        return file(settings.web_dir / "shared" / name) if name == "market-shell.css" else JSONResponse({"error": "静态资源不存在"}, status_code=404)
