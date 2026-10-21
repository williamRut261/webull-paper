"""Daily independent-strategy and equal-weight portfolio return ledger.

READ-ONLY research only. This processes externally verified daily net returns;
it does not invent prices, collect orders, or query a broker. Incomplete or
unattributed observations fail closed and cannot be ranked as real returns.
"""
import argparse
from datetime import date
import json
import math
from pathlib import Path

SLEEVES = ("beethoven", "inout", "rsi_trend", "claude_orb")
MODES = frozenset(("backtest", "paper", "live"))


class DailyLedgerError(ValueError):
    pass


def finite(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DailyLedgerError(what + " must be numeric")
    v = float(value)
    if not math.isfinite(v):
        raise DailyLedgerError(what + " must be finite")
    return v


def iso(value):
    if not isinstance(value, str):
        raise DailyLedgerError("Date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise DailyLedgerError("Date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise DailyLedgerError("Date must be canonical YYYY-MM-DD")
    return parsed


def fresh(initial_capital=10000, mode="paper"):
    capital = finite(initial_capital, "initial capital")
    if capital <= 0 or mode not in MODES:
        raise DailyLedgerError("Invalid initial capital or recording mode")
    return dict(schema_version=1, mode=mode, starting_capital=capital,
                initial_sleeve_capital=capital / 4,
                independent_sleeve_equity={key: capital / 4 for key in SLEEVES},
                equal_weight_rebalanced_portfolio_equity=capital, entries=[])


def append(ledger, observation):
    """Append a FULL common trading session, preserving independent sleeve NAVs.

    Strategy values compound separately from their original 25% virtual
    starting capital. The portfolio NAV uses daily rebalanced equal weights
    (25% exposure for every strategy EVERY day); those two NAV accounting
    models are intentionally separate and MUST NOT be conflated.
    """
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("entries"), list):
        raise DailyLedgerError("Unknown ledger schema")
    if not isinstance(observation, dict):
        raise DailyLedgerError("Observation must be an object")
    day = iso(observation.get("date"))
    if ledger["entries"] and day <= iso(ledger["entries"][-1]["date"]):
        raise DailyLedgerError("Duplicate or out-of-order trading date")
    if observation.get("mode") != ledger.get("mode"):
        raise DailyLedgerError("Cannot mix backtest/paper/live measurements")
    results = observation.get("strategies")
    if not isinstance(results, dict) or set(results) != set(SLEEVES):
        raise DailyLedgerError("All four sleeves are required; no fake zero returns")
    pct = {}
    meta = {}
    for sleeve in SLEEVES:
        row = results[sleeve]
        if not isinstance(row, dict):
            raise DailyLedgerError("Missing observation for " + sleeve)
        value = finite(row.get("net_return"), sleeve + " net_return")
        if value < -1:
            raise DailyLedgerError("A fully funded unlevered sleeve cannot lose over 100%")
        source = row.get("evidence")
        if not isinstance(source, str) or not source.strip() or source.strip().lower() in (
                "example", "synthetic", "unknown", "tbd", "none"):
            raise DailyLedgerError("Verifiable evidence identifier needed for " + sleeve)
        as_of = row.get("signal_as_of")
        if iso(as_of) > day:
            raise DailyLedgerError("Future signal not allowed for " + sleeve)
        timing = row.get("timing")
        if timing not in ("prior_close", "intraday"):
            raise DailyLedgerError("Unknown timing for " + sleeve)
        if timing == "prior_close" and iso(as_of) >= day:
            raise DailyLedgerError("Close-to-close signals must predate observation day")
        if timing == "intraday" and iso(as_of) != day:
            raise DailyLedgerError("Intraday evidence must belong to observation day")
        pct[sleeve] = value
        meta[sleeve] = {"net_return": value, "evidence": source.strip(),
                        "signal_as_of": as_of, "timing": timing}
    prior = {key: finite(ledger["independent_sleeve_equity"][key], key)
             for key in SLEEVES}
    combined_prior = finite(ledger["equal_weight_rebalanced_portfolio_equity"],
                            "combined equity")
    if min(*prior.values(), combined_prior) < 0:
        raise DailyLedgerError("Negative equity in prior ledger")
    next_equities = {key: prior[key] * (1 + pct[key]) for key in SLEEVES}
    combined_day_return = sum(pct.values()) / 4
    next_combined = combined_prior * (1 + combined_day_return)
    result = {}
    for key in SLEEVES:
        start = ledger["initial_sleeve_capital"]
        result[key] = {
            **meta[key],
            "net_return_pct": round(100*pct[key], 6),
            "independent_daily_pnl": round(next_equities[key]-prior[key], 6),
            "independent_equity": round(next_equities[key], 6),
            "independent_total_return_pct": round(100*(next_equities[key]/start - 1), 6)
        }
    ranking = sorted(SLEEVES, key=lambda s: (-pct[s], s))
    entry = {"date": str(day),
             "ranking_by_daily_return": list(ranking),
             "strategies": result,
             "equal_weight_portfolio_daily_return_pct": round(combined_day_return*100, 6),
             "equal_weight_portfolio_daily_pnl": round(next_combined-combined_prior, 6),
             "equal_weight_rebalanced_portfolio_equity": round(next_combined, 6),
             "equal_weight_portfolio_total_return_pct": round(
                 100*(next_combined / ledger["starting_capital"] - 1), 6)}
    updated = {**ledger,
               "independent_sleeve_equity": next_equities,
               "equal_weight_rebalanced_portfolio_equity": next_combined,
               "entries": [*ledger["entries"], entry]}
    return updated, entry


def markdown(entry, mode):
    """Generate an unambiguous comparable four-strategy session report."""
    rows = [
        "# Four-strategy daily leaderboard — " + entry["date"],
        "",
        "**" + mode.upper() + "**, not broker-verified unless supporting evidence explicitly establishes it.",
        "",
        "Each strategy started with 25% of original research capital.",
        "Separate strategy NAVs compound independently; combined NAV assumes DAILY 25/25/25/25 rebalancing.",
        "",
        "| Rank | Strategy | Daily net return | Daily P&L (virtual $) | Cumulative net return | Equity (virtual $) |",
        "|---:|---|---:|---:|---:|---:|"
    ]
    labels = {"beethoven": "Beethoven", "inout": "In & Out",
              "rsi_trend": "RSI Trend", "claude_orb": "Claude ORB"}
    for rank, sleeve in enumerate(entry["ranking_by_daily_return"], 1):
        item = entry["strategies"][sleeve]
        rows.append("| {} | {} | {:+.3f}% | {:+,.2f} | {:+.3f}% | {:,.2f} |".format(
            rank, labels[sleeve], item["net_return_pct"], item["independent_daily_pnl"],
            item["independent_total_return_pct"], item["independent_equity"]))
    rows += ["", "**Equal-weight combined portfolio:** {:+.3f}% today ({:+,.2f} virtual $); "
             "{:+.3f}% cumulative; {:,.2f} virtual $ equity.".format(
                 entry["equal_weight_portfolio_daily_return_pct"],
                 entry["equal_weight_portfolio_daily_pnl"],
                 entry["equal_weight_portfolio_total_return_pct"],
                 entry["equal_weight_rebalanced_portfolio_equity"]),
             "",
             "## Evidence"]
    for sleeve in SLEEVES:
        item = entry["strategies"][sleeve]
        rows.append("- {}: {} (signal {}, {})".format(
            labels[sleeve], item["evidence"], item["signal_as_of"], item["timing"]))
    return "\n".join(rows) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--observation", required=True, help="JSON with four documented REAL daily returns")
    p.add_argument("--ledger", required=True, help="Persistent private/research ledger JSON")
    p.add_argument("--report", required=True, help="Markdown report for this day")
    p.add_argument("--initial-capital", type=float, default=10000)
    args = p.parse_args()
    obs = json.loads(Path(args.observation).read_text())
    dest = Path(args.ledger)
    ledger = json.loads(dest.read_text()) if dest.exists() else fresh(args.initial_capital, obs["mode"])
    updated, entry = append(ledger, obs)
    report = markdown(entry, updated["mode"])
    # No mutation until validation is complete. Caller should retain files.
    dest.parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(updated, indent=2, sort_keys=True)+"\n")
    Path(args.report).write_text(report)
    print(report)


if __name__ == "__main__":
    main()
