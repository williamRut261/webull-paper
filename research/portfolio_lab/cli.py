"""Offline portfolio planning; cannot submit trades to any account."""
import argparse
import json
from pathlib import Path
import pandas as pd
from .portfolio import combine, PortfolioError
from .inout import inout_from_closes, RegimeState


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--signals", required=True)
    p.add_argument("--current", help="Optional JSON current symbol->portfolio weight")
    p.add_argument("--inout-daily", help="Optional WIDE CSV: date,QQQ,XLI,...; 252+ days")
    p.add_argument("--as-of", required=True, help="Completed signal date, YYYY-MM-DD")
    p.add_argument("--out", help="Optional output JSON file")
    args = p.parse_args()
    conf = json.loads(Path(args.config).read_text())
    doc = json.loads(Path(args.signals).read_text())
    if doc.get("as_of") != args.as_of:
        raise PortfolioError("Signals must match the requested completed as-of session")
    signals = dict(doc["targets"])
    regime = None
    if args.inout_daily:
        if not conf.get("budgets", {}).get("inout"):
            raise PortfolioError("In & Out sleeve not funded")
        frame = pd.read_csv(args.inout_daily, parse_dates=["date"]).set_index("date")
        frame = frame.loc[frame.index <= pd.Timestamp(args.as_of)]
        if frame.empty or frame.index[-1].strftime("%Y-%m-%d") != args.as_of:
            raise PortfolioError("Missing In & Out historical close on signal date")
        last = doc.get("prior_inout_state", {})
        state = RegimeState(**last) if last else RegimeState()
        regime = inout_from_closes(frame, state)
        signals["inout"] = regime.weights
    current = json.loads(Path(args.current).read_text()) if args.current else {}
    plan = combine(conf["budgets"], signals,
                   cash_reserve=conf.get("cash_reserve", .01),
                   max_symbol_weight=conf.get("max_symbol_weight", .99),
                   current_weights=current)
    result = dict(plan.to_dict(), as_of=args.as_of)
    if regime:
        result["inout_state_for_NEXT_run"] = vars(regime.state)
        result["inout_shock_signals"] = list(regime.triggered)
    raw = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(raw)
    print(raw)


if __name__ == "__main__":
    main()
