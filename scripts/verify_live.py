"""Observe an already-running service. Does not call Binance directly."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def audit(snapshot: dict) -> dict:
    checked = 0
    samples = {}
    spot = snapshot["index_price"]
    for item in snapshot["contracts"]:
        annual = item.get("annualized_pct")
        if annual is None:
            continue
        strike = item["strike"]
        generation = item["annualized_calculated_at_ms"]
        remaining = (item["expiry_ms"] - generation) / 1000
        intrinsic = max(spot - strike, 0) if item["side"] == "CALL" else max(strike - spot, 0)
        tv = item["bid"] - intrinsic
        capital = spot if item["side"] == "CALL" else strike
        period = tv / capital * 100
        expected = period * 31_536_000 / remaining
        for actual, wanted in ((annual, expected), (item["time_value"], tv), (item["period_return_pct"], period)):
            if not math.isclose(actual, wanted, rel_tol=1e-10, abs_tol=1e-8):
                raise AssertionError(f"Calculation mismatch: {item['symbol']}")
        checked += 1
        key = (item["expiry_ms"], item["side"])
        if key not in samples or abs(strike-spot) < abs(samples[key]["strike"]-spot):
            samples[key] = {name: item.get(name) for name in (
                "symbol", "side", "strike", "bid", "intrinsic_value", "time_value",
                "period_return_pct", "annualized_pct", "annualized_calculated_at_ms",
                "exercise_probability_pct", "mark_iv", "risk_free_interest", "delta",
            )}
    if not checked:
        raise AssertionError("No valid live annualized values were available")
    return {"checked_contracts": checked, "samples": list(samples.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8780", help="Service URL including its prefix, e.g. http://127.0.0.1:8780/options for Compose")
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", type=Path, default=Path("runtime/verification/live.json"))
    args = parser.parse_args()
    if args.generations < 1 or args.timeout <= 0:
        parser.error("generations and timeout must be positive")
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "generations": [], "request_errors": []}
    deadline = time.monotonic() + args.timeout
    seen = set()
    while time.monotonic() < deadline and len(seen) < args.generations:
        try:
            with urllib.request.urlopen(args.url.rstrip("/") + "/api/v1/bitcoin/snapshot", timeout=8) as response:
                snapshot = json.load(response)
            generation = snapshot.get("market_generation_ms")
            if generation and generation not in seen and not snapshot["status"]["stale"]:
                verified = audit(snapshot)
                report["generations"].append({
                    "market_generation_ms": generation, "fetched_at": snapshot["fetched_at"],
                    "status": snapshot["status"], "contract_count": len(snapshot["contracts"]),
                    **verified,
                })
                seen.add(generation)
                print(f"Generation {len(seen)}: {snapshot['fetched_at']}, verified {verified['checked_contracts']} contracts", flush=True)
        except (OSError, ValueError) as exc:
            report["request_errors"].append({"type": type(exc).__name__, "message": str(exc)})
        if len(seen) < args.generations:
            time.sleep(min(5, max(0, deadline-time.monotonic())))
    report["passed"] = len(seen) >= args.generations
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
