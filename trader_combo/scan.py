"""Invoke the original Day Trader Skill 5-minute ORB scanner unchanged.

Signal source: unofficial public Yahoo bars. Never an execution price.
Only today's very recent, fully-confirmed setups may be considered.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile

from trader_combo.universe import CANDIDATES, MAX_POSITIONS

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "vendor/day_trader_skill/trader-scanner/scan.py"


def select_recent_signals(report, now, positions=MAX_POSITIONS):
    if not isinstance(report, dict) or report.get("mode") != "orb":
        raise RuntimeError("Unexpected OG scanner output")
    if report.get("source") != "yahoo" or report.get("unconfirmed") != 0:
        raise RuntimeError("Incomplete or unexpected OG scanner verification")
    if report.get("universe") != len(CANDIDATES):
        raise RuntimeError("Missing scanner ticker coverage")
    if report.get("failed", 0) > len(CANDIDATES) // 5:
        raise RuntimeError("Too many incomplete public market charts")
    if now.tzinfo is None:
        raise RuntimeError("Timezone required for scanner")
    if not isinstance(report.get("hits"), list):
        raise RuntimeError("Missing scanner hits")
    selected = []
    for hit in report["hits"]:
        if not isinstance(hit, dict):
            raise RuntimeError("Malformed scanner hit")
        symbol = hit.get("symbol")
        if symbol not in CANDIDATES:
            raise RuntimeError("Scanner returned unapproved ticker")
        if hit.get("close_date") is not None and hit["close_date"] != now.date().isoformat():
            raise RuntimeError("Stale scanner daily bar")
        try:
            from datetime import datetime as dt
            label = hit["at"]
            parsed = dt.strptime(label, "%I:%M %p") if "M" in label else dt.strptime(label, "%H:%M")
            found = now.replace(hour=parsed.hour, minute=parsed.minute,
                                second=0, microsecond=0)
            age = (now - found).total_seconds()
            pct = float(hit["pct_over"])
            low = float(hit["or_low"])
            high = float(hit["or_high"])
            price = float(hit["price"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError("Invalid scanner breakout evidence") from exc
        if not 0 <= age <= 600 or not 0.10 <= pct <= 3.0:
            continue
        if not 0 < low < high < price:
            continue
        if symbol not in {x["symbol"] for x in selected}:
            selected.append({"symbol": symbol, "range_low": low,
                             "range_high": high, "signal_price": price,
                             "breakout_percent": pct, "signal_age_seconds": age})
        if len(selected) >= positions:
            break
    return selected


def run_scan(now):
    if not SCANNER.is_file():
        raise RuntimeError("Missing vendored OG trader scanner")
    if now.tzinfo is None:
        raise RuntimeError("Timezone-aware scan time required")
    with tempfile.TemporaryDirectory(prefix="paper-trader-") as tmp:
        out = Path(tmp) / "orb.json"
        command = [sys.executable, str(SCANNER), "orb", "--symbols",
                   ",".join(sorted(CANDIDATES)), "--min-price", "5",
                   "--min-volume", "100000", "--max-confirm", "40",
                   "--out", str(out), "--quiet"]
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                text=True, timeout=240, check=False)
        # Upstream returns 1 for no hits as well as for an error.
        if not out.is_file():
            raise RuntimeError("OG scanner failed: " + result.stderr[-250:])
        report = json.loads(out.read_text(encoding="utf-8"))
        if result.returncode not in (0, 1):
            raise RuntimeError("Unexpected scanner process exit")
        return select_recent_signals(report, now)
