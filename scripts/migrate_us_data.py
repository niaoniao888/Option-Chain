"""Validate and optionally copy only private US watchlist/guide data; never overwrite."""
from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path

from options_panel.us_equities.guide_store import GuideStore
from options_panel.us_equities.watchlist_store import WatchlistStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    pending = []
    for name in ("watchlist.json", "options-guide.json"):
        source, target = args.source / name, args.destination / name
        if not source.is_file():
            continue
        raw = source.read_bytes()
        if name == "watchlist.json":
            WatchlistStore(target)._decode(raw)
        else:
            GuideStore._decode(raw)
        if target.exists():
            if target.read_bytes() != raw:
                raise SystemExit(f"Refusing to overwrite existing {name}")
            print(f"Unchanged: {name}")
            continue
        pending.append((name, target, raw))
    for name, target, raw in pending:
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".migration-", dir=target.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Atomic publication without replacing a concurrently created target.
                os.link(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        print(f"{'Copied' if args.apply else 'Would copy'}: {name}; sha256={hashlib.sha256(raw).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
