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
if __name__=="__main__":unittest.main()
