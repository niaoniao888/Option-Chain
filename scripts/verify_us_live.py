"""Observe three local US snapshots and independently verify frozen calculations."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(snapshot):
    counts = {"yields": 0, "probabilities": 0}
    for row in snapshot["contracts"]:
        s, k = snapshot["underlying_price"], row["strike"]
        call = row["side"] == "CALL"
        if row["annualized_pct"] is not None:
            tv = row["bid"] - max(s - k if call else k - s, 0)
            period = tv / (s if call else k) * 100
            seconds = (instant(row["expires_at_utc"]) - instant(row["calculation_basis_utc"])).total_seconds()
            if not (math.isclose(period, row["period_return_pct"], rel_tol=1e-9, abs_tol=1e-9)
                    and math.isclose(period * 31536000 / seconds, row["annualized_pct"], rel_tol=1e-9, abs_tol=1e-9)):
                raise ValueError("Yield calculation mismatch")
            counts["yields"] += 1
        if row["exercise_probability_pct"] is not None:
            years = (instant(row["expires_at_utc"]) - instant(row["probability_basis_utc"])).total_seconds() / 31536000
            sigma = row["implied_volatility"]
            d2 = (math.log(s / k) - sigma * sigma * years / 2) / (sigma * math.sqrt(years))
            probability = 50 * math.erfc(-(d2 if call else -d2) / math.sqrt(2))
            if not math.isclose(probability, row["exercise_probability_pct"], rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError("Probability calculation mismatch")
            counts["probabilities"] += 1
    if not counts["yields"] or not counts["probabilities"]:
        raise ValueError("Snapshot must contain valid yields and probabilities to verify")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8780")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeout", type=float, default=420)
    args = parser.parse_args()
    client, sequence, seen = uuid.uuid4().hex, 0, set()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline and len(seen) < 3:
        sequence += 1
        query = urllib.parse.urlencode(dict(symbol=args.symbol, client_id=client, active=1, activity_seq=sequence))
        with urllib.request.urlopen(args.url.rstrip("/") + "/api/v1/us-equities/snapshot?" + query, timeout=15) as response:
            snapshot = json.load(response)
        stamp = snapshot.get("fetched_at")
        if stamp and stamp not in seen and snapshot.get("fetch_health") == "healthy":
            checks = verify(snapshot)
            if not checks["yields"]:
                raise SystemExit("No valid yields to verify")
            seen.add(stamp)
            print(json.dumps({"round": len(seen), "market_status": snapshot["market_status"], **checks}), flush=True)
        if len(seen) < 3:
            time.sleep(5)
    if len(seen) != 3:
        raise SystemExit("Did not observe three successful snapshots before timeout")
    print("PASS: three generations; calculations verified; no raw market data exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
