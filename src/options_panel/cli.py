from __future__ import annotations

import argparse
import dataclasses
import threading
import webbrowser

import uvicorn

from options_panel.api import create_app
from options_panel.config import Settings, normalize_base_path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="比特币期权只读面板")
    result.add_argument("--host")
    result.add_argument("--port", type=int)
    result.add_argument("--base-path")
    result.add_argument("--open", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings.from_env()
    settings = dataclasses.replace(
        settings,
        host=args.host or settings.host,
        port=args.port or settings.port,
        base_path=normalize_base_path(args.base_path) if args.base_path is not None else settings.base_path,
    )
    if args.open:
        url = f"http://{settings.host}:{settings.port}{settings.base_path}/"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1, proxy_headers=settings.forwarded_headers, forwarded_allow_ips="127.0.0.1" if settings.forwarded_headers else "")
    return 0
