"""Read-only, informational report from the existing Webull PAPER runner's log.

Does not import SDKs, fetch broker accounts, simulate missing observations,
modify the original strategy, or affect the order pathway.
"""
import argparse
import json
import math
from pathlib import Path

from strategy_engine import ORIGINAL_EXECUTION_ASSETS

MARKERS = ("PAPER_AUTO_SIGNAL", "PAPER_REBALANCE_COMPLETE",
           "PAPER_TWO_SAMPLE_AGREEMENT")
KNOWN_LEVERAGED = frozenset(
    "GDXU GDXD TQQQ SQQQ UVXY SPXL SPXU UPRO TECL TECS "
    "FAS FAZ SOXL SOXS TMF NVDL BITX AMDL GGLL QLD".split())


def parse_events(log):
    events = {marker: [] for marker in MARKERS}
    for line in log.splitlines():
        for marker in MARKERS:
            anchor = marker + " "
            position = line.find(anchor)
            if position < 0:
                continue
            data = json.loads(line[position + len(anchor):])
            if not isinstance(data, dict):
                raise ValueError("Non-object log event: " + marker)
            events[marker].append(data)
            break
    return events


def safe_targets(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("Missing or invalid target weights")
    if set(value) - ORIGINAL_EXECUTION_ASSETS:
        raise ValueError("Signal contains non-Beethoven assets")
    weights = {}
    for ticker, weight in value.items():
        if isinstance(weight, bool) or not isinstance(weight, (float, int)):
            raise ValueError("Invalid target weight")
        if not math.isfinite(weight) or weight <= 0 or weight > 0.99:
            raise ValueError("Nonfinite or out-of-range target")
        weights[ticker] = float(weight)
    if not math.isclose(sum(weights.values()), 0.99, rel_tol=0, abs_tol=1e-6):
        raise ValueError("Targets do not total 99%")
    return dict(sorted(weights.items()))


def build_report(log):
    basic = {
        "mode": "read_only_paper_research",
        "authority": "ADVISORY_ONLY_NOT_AN_EXECUTION_GATE",
        "broker_orders_submitted_by_research": 0,
        "strategy_overrides": False,
        "proven_profitability": False,
        "timemachine_run": False,
        "note": "Parsed runner logs, not independent broker/account verification; "
                "intraday Time Machine requires its own historical bars and plan."
    }
    try:
        events = parse_events(log)
        signals = events["PAPER_AUTO_SIGNAL"]
        if not signals:
            return {**basic, "status": "NO_VERIFIED_LOG_SIGNAL",
                    "warning": "No PAPER_AUTO_SIGNAL found; do not infer a trade."}
        if len(signals) != 1:
            raise ValueError("Expected exactly one PAPER_AUTO_SIGNAL")
        signal = signals[0]
        if signal.get("paper_only") is not True:
            raise ValueError("Signal did not assert paper-only trading")
        targets = safe_targets(signal.get("targets"))
        complete = events["PAPER_REBALANCE_COMPLETE"]
        if len(complete) > 1:
            raise ValueError("Multiple completion events")
        completion = complete[0] if complete else None
        count = completion.get("order_count") if completion else None
        if count is not None and (isinstance(count, bool) or
                                  not isinstance(count, int) or count < 0):
            raise ValueError("Invalid completion order count")
        maximum = max(targets.values())
        notes = []
        if maximum >= 0.75:
            notes.append("High single-asset concentration: not diversified.")
        risky = sorted(set(targets) & KNOWN_LEVERAGED)
        if risky:
            notes.append("Selected assets include leveraged/inverse/volatility "
                         "ETFs; a 99% equity allocation is not a 99% risk cap.")
        if completion is None:
            notes.append("No completed rebalance marker; execution may have failed "
                         "or not finished. Do not infer a fill.")
        return {**basic, "status": "PAPER_LOG_REBALANCE_COMPLETE" if completion
                else "PAPER_LOG_SIGNAL_ONLY", "date": signal.get("date"),
                "targets": targets, "max_symbol_weight": maximum,
                "known_high_risk_tickers": risky, "review_notes": notes,
                "completion_logged": completion is not None,
                "order_count_reported_by_runner": count,
                "independent_fill_verification_by_research": False}
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return {**basic, "status": "INVALID_PAPER_LOG",
                "warning": str(exc)[:180]}


def main(argv=None):
    cli = argparse.ArgumentParser()
    cli.add_argument("--log", type=Path, default=Path("logs/webull-paper.log"))
    cli.add_argument("--output", type=Path, default=Path("logs/beethoven-research.json"))
    args = cli.parse_args(argv)
    report = build_report(args.log.read_text(encoding="utf-8")
                          if args.log.exists() else "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("BEETHOVEN_RESEARCH_ADVISORY " +
          json.dumps({"status": report["status"],
                      "completion_logged": report.get("completion_logged", False),
                      "orders_submitted_by_research": 0}, sort_keys=True),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
