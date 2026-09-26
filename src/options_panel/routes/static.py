from __future__ import annotations

from pathlib import Path, PurePosixPath

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
        allowed_set = set(allowed)
        root = (settings.web_dir / directory).resolve()
        def handler(asset_path: str):
            normalized = PurePosixPath(asset_path)
            safe = (asset_path in allowed_set and not normalized.is_absolute()
                    and ".." not in normalized.parts and "" not in normalized.parts)
            target = (root / Path(*normalized.parts)).resolve() if safe else root
            return (file(target) if safe and target.is_relative_to(root)
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
            app.add_api_route(p(route + "{asset_path:path}"), asset_handler(directory, assets), methods=["GET"],
                              name=endpoint + "_asset")
