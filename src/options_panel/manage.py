"""Offline management CLI for persistent US-equities documents."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from options_panel.config import Settings
from options_panel.us_equities.guide_store import GuideStore
from options_panel.us_equities.watchlist_store import WatchlistStore


def _data_dir(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Settings.from_env().us_data_dir


def _atomic_export(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            GuideStore._atomic_write(backup, path.read_bytes())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="期权面板离线数据管理（不启动采集器或 HTTP 服务）")
    parser.add_argument("--data-dir", help="运行数据目录；默认读取 OPTIONS_US_DATA_DIR")
    commands = parser.add_subparsers(dest="command", required=True)
    watchlist = commands.add_parser("watchlist", help="管理美股自选")
    watch_actions = watchlist.add_subparsers(dest="action", required=True)
    watch_actions.add_parser("list")
    watch_actions.add_parser("revision")
    for action in ("add", "remove"):
        item = watch_actions.add_parser(action)
        item.add_argument("symbol")
        item.add_argument("--revision", required=True, help="list 输出中的当前 revision")
    guide = commands.add_parser("guide", help="导入或导出个人说明")
    guide_actions = guide.add_subparsers(dest="action", required=True)
    guide_actions.add_parser("revision")
    export = guide_actions.add_parser("export")
    export.add_argument("path", type=Path)
    import_ = guide_actions.add_parser("import")
    import_.add_argument("path", type=Path)
    import_.add_argument("--revision", required=True, help="当前运行数据的 revision")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = _data_dir(args.data_dir)
    try:
        if args.command == "watchlist":
            store = WatchlistStore(data_dir / "watchlist.json")
            if args.action == "list":
                result = store.get()
            elif args.action == "revision":
                print(store.get()["revision"])
                return 0
            elif args.action == "add":
                result = store.add_document(args.symbol, args.revision)
            else:
                result = store.remove_document(args.symbol, args.revision)
        else:
            store = GuideStore(data_dir / "options-guide.json")
            if args.action == "revision":
                print(store.get()["revision"])
                return 0
            elif args.action == "export":
                result = store.get()
                _atomic_export(args.path.expanduser().resolve(), result)
                result = {"path": str(args.path), "revision": result["revision"]}
            else:
                document = json.loads(args.path.expanduser().resolve().read_text(encoding="utf-8"))
                if not isinstance(document, dict) or set(document) != {"revision", "updated_at", "sections"}:
                    raise ValueError("说明导入文件结构无效")
                if document["revision"] != args.revision:
                    raise ValueError("导入文件 revision 与 --revision 不一致")
                result = store.update(document["sections"], args.revision)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
