"""No broker calls. Intraday scanner tests with synthetic bars."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from trader_combo.universe import CANDIDATES
from backtests.compare import read_bars, morning

class ResearchTests(unittest.TestCase):
    def test_missing_bars_must_never_look_like_zero_pnl(self):
        pnl,trades,info=morning("2026-10-19",{},10000)
        self.assertIsNone(pnl)
        self.assertEqual(trades,[])
        self.assertEqual(info["coverage"],0)

    def test_complete_bar_sequence_and_first_hit(self):
        sym=sorted(CANDIDATES)[0]
        times=pd.date_range("2026-10-19 09:30",periods=78,
                            freq="5min",tz="America/New_York")
        rows=[]
        for i,t in enumerate(times):
            px=100 if i<8 else 101.
            rows.append({"datetime":t.isoformat(),"symbol":sym,"open":px,
                         "high":100.5 if i<3 else px+.1,
                         "low":99.5 if i<3 else px-.1,
                         "close":px,"volume":20000})
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/"bar.csv"
            pd.DataFrame(rows).to_csv(f,index=False)
            got=read_bars(f)
            self.assertIn(("2026-10-19",sym),got)
            pnl,trades,info=morning("2026-10-19",got,10000)
            self.assertIsNone(pnl)
            self.assertEqual(info["coverage"],1)

    def test_contiguous_windows_are_not_stitched(self):
        from unittest.mock import patch
        from backtests.compare import run
        class FakeEvaluator:
            def __init__(self, root, data):
                self.data = data
            def evaluate(self):
                if self.data.index[-1] == pd.Timestamp("2024-01-03"):
                    raise ValueError("selected ETF not yet listed")
                return {"ZZZ": 1.0}
        dates = pd.bdate_range("2024-01-02", periods=9)
        frame = pd.DataFrame({"ZZZ": [100+i for i in range(len(dates))]}, index=dates)
        with patch("backtests.compare.load_strategy", return_value=None), patch(
                "backtests.compare.Evaluator", FakeEvaluator):
            long, match, trades, coverage = run(frame, {}, "2024-01-01", "2024-01-31", 0)
        self.assertEqual(coverage["daily_skipped_sessions"], 1)
        self.assertEqual(len(coverage["valid_daily_windows"]), 2)
        self.assertEqual(long.date.iloc[0], "2024-01-05")
        self.assertEqual(long.date.iloc[-1], "2024-01-12")
        self.assertTrue(match.empty)

    def test_drawdown_includes_first_session_loss(self):
        from backtests.compare import stats
        frame = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"],
                              "equity": [9000.0, 9500.0]})
        got = stats(frame, "equity")
        self.assertEqual(got["max_drawdown_pct"], -10.0)

    def test_original_scanner_allows_at_most_twenty_pct_missing(self):
        from backtests.compare import morning
        day="2026-10-19"
        times = pd.date_range("2000-01-01 09:30", periods=10, freq="5min").strftime("%H:%M")
        q = pd.DataFrame({"open":[10.0]*10, "high":[11.0]*10,
                          "low":[9.0]*10, "close":[10.0]*10,
                          "volume":[20000.0]*10}, index=times)
        syms=sorted(CANDIDATES)
        allowed_missing=len(syms)//5
        bars={(day,s):q for s in syms[allowed_missing:]}
        pnl,orders,detail=morning(day,bars,10000)
        self.assertEqual(pnl,0.)
        self.assertEqual(len(orders),0)
        self.assertEqual(detail["coverage"],len(syms)-allowed_missing)
        self.assertEqual(len(detail["missing_symbols"]),allowed_missing)
        bars.pop((day,syms[allowed_missing]))
        pnl,orders,detail=morning(day,bars,10000)
        self.assertIsNone(pnl)

if __name__=="__main__":unittest.main()
