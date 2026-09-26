from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from options_panel.assembly import Platform
from options_panel.content.guide_store import GuideError
from options_panel.us_equities.guide_store import GuideError as UsGuideError
from options_panel.us_equities.market_service import ClientCapacityError
from options_panel.us_equities.watchlist_store import normalize_symbol


def install_market_routes(app: FastAPI, platform: Platform) -> None:
    base = platform.settings.base_path
    p = lambda path: (base + path) or "/"

    def unavailable(market: str):
        record = platform.records.get(market)
        detail = record.initialization_error if record else "market not registered"
        return JSONResponse({"error": "市场模块不可用", "detail": detail}, status_code=503)

    for registration in platform.registry.registrations():
        if registration.route_installer is not None:
            registration.route_installer(app, platform, registration)
        if registration.api_profile != "generic":
            continue
        market_id = registration.descriptor.market_id

        def snapshot_handler(selected_market: str):
            def handler(instrument: str | None = None):
                runtime = platform.runtime(selected_market)
                if runtime is None:
                    return unavailable(selected_market)
                selected = instrument or runtime.descriptor.default_instrument
                key = platform.snapshot_cache.key(
                    selected_market, runtime.descriptor.provider_id, selected
                )
                return Response(
                    platform.snapshot_cache.body(
                        key, lambda: runtime.snapshot_envelope(selected).as_dict(),
                    ), media_type="application/json",
                    headers={"Cache-Control": "public, max-age=1"},
                )
            return handler

        def health_handler(selected_market: str):
            def handler():
                record = platform.records.get(selected_market)
                if record is None or record.runtime is None:
                    return unavailable(selected_market)
                return JSONResponse(record.public_health(), headers={"Cache-Control": "no-store"})
            return handler

        app.add_api_route(p(f"/api/v1/{market_id}/snapshot"), snapshot_handler(market_id), methods=["GET"],
                          name=f"{market_id}_snapshot")
        app.add_api_route(p(f"/api/v1/{market_id}/health"), health_handler(market_id), methods=["GET"],
                          name=f"{market_id}_health")

    @app.get(p("/api/v1/bitcoin/snapshot"))
    @app.get(p("/api/snapshot"))
    def snapshot():
        runtime = platform.runtime("bitcoin")
        if runtime is None: return unavailable("bitcoin")
        key = platform.snapshot_cache.key("bitcoin", runtime.provider_id, "BTCUSDT")
        return Response(platform.snapshot_cache.body(key, runtime.state.snapshot), media_type="application/json", headers={"Cache-Control": "public, max-age=1"})

    @app.get(p("/api/v1/bitcoin/health"))
    @app.get(p("/api/health"))
    def health():
        runtime = platform.runtime("bitcoin")
        return JSONResponse(runtime.state.health(), headers={"Cache-Control": "no-store"}) if runtime else unavailable("bitcoin")

    @app.get(p("/api/v1/bitcoin/options-guide"))
    @app.get(p("/api/options-guide"))
    def options_guide():
        runtime = platform.runtime("bitcoin")
        if runtime is None: return unavailable("bitcoin")
        try: return JSONResponse(runtime.guide.get(), headers={"Cache-Control": "no-store"})
        except GuideError as exc: return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/health"))
    def us_health():
        runtime = platform.runtime("us-equities")
        return JSONResponse(runtime.health(), headers={"Cache-Control": "no-store"}) if runtime else unavailable("us-equities")

    @app.get(p("/api/v1/us-equities/watchlist"))
    def us_watchlist():
        runtime = platform.runtime("us-equities")
        if runtime is None: return unavailable("us-equities")
        try: return JSONResponse(runtime.watchlist.get(), headers={"Cache-Control": "no-store"})
        except ValueError as exc: return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/options-guide"))
    def us_options_guide():
        runtime = platform.runtime("us-equities")
        if runtime is None: return unavailable("us-equities")
        try: return JSONResponse(runtime.guide.get(), headers={"Cache-Control": "no-store"})
        except UsGuideError as exc: return JSONResponse({"error": str(exc)}, status_code=503)

    @app.get(p("/api/v1/us-equities/snapshot"))
    def us_snapshot(request: Request):
        runtime = platform.runtime("us-equities")
        if runtime is None: return unavailable("us-equities")
        query = request.query_params
        values = query.getlist("symbol")
        if len(values) != 1: return JSONResponse({"error": "必须指定唯一 symbol"}, status_code=400)
        try: symbol = normalize_symbol(values[0])
        except ValueError as exc: return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            if symbol not in runtime.watchlist.list(): return JSONResponse({"error": "symbol 不在自选列表"}, status_code=404)
        except ValueError as exc: return JSONResponse({"error": str(exc)}, status_code=503)
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
        if len(sequences) > 1 or (sequences and (not re.fullmatch(r"\d{1,16}", sequences[0]) or int(sequences[0]) > 9007199254740991)):
            return JSONResponse({"error": "activity_seq 无效"}, status_code=400)
        active = active_values[0] == "1" if active_values else None
        try:
            payload = runtime.market.snapshot(
                symbol, if_version=versions[0] if versions else None,
                client_id=clients[0] if clients else None, active=active,
                activity_seq=int(sequences[0]) if sequences else None,
            )
        except ClientCapacityError as exc:
            return JSONResponse({"error": str(exc)}, status_code=429, headers={"Retry-After": "15", "Cache-Control": "no-store"})
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
