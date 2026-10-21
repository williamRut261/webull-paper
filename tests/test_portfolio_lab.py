"""Offline multi-sleeve proof of noninterference; no credentials or orders."""
import math
import unittest
import numpy as np
import pandas as pd
from research.portfolio_lab.portfolio import combine,PortfolioError
from research.portfolio_lab.inout import inout_from_closes,RegimeState


class PortfolioLabTests(unittest.TestCase):
    def test_overlap_nets_target_and_preserves_virtual_ownership(self):
        x=combine({"beethoven":.60,"inout":.20,"rsi":.10,"orb":.09},
                  {"beethoven":{"QQQ":.5,"TLT":.5},"inout":{"QQQ":1},
                   "rsi":{"GLD":1},"orb":{"XLE":1}},
                  current_weights={"QQQ":.55,"TLT":.3,"GLD":.1,"XLE":.05})
        self.assertAlmostEqual(x.targets["QQQ"],.5)
        self.assertAlmostEqual(x.targets["TLT"],.3)
        self.assertAlmostEqual(x.targets["GLD"],.1)
        self.assertAlmostEqual(x.targets["XLE"],.09)
        self.assertAlmostEqual(x.cash_weight,.01)
        self.assertAlmostEqual(x.changes["QQQ"],-.05)
        self.assertAlmostEqual(x.changes["XLE"],.04)
        self.assertEqual(len(x.changes),2)
        self.assertAlmostEqual(x.sleeve_ledger["beethoven"]["QQQ"],.3)
        self.assertAlmostEqual(x.sleeve_ledger["inout"]["QQQ"],.2)

    def test_missing_funded_sleeve_fails_closed(self):
        with self.assertRaisesRegex(PortfolioError,"missing signals"):
            combine({"beethoven":.8,"inout":.19},{"beethoven":{"QQQ":1}})

    def test_explicit_cash_signal_is_not_donated_to_other_sleeve(self):
        x=combine({"beethoven":.8,"inout":.19},{"beethoven":{"QQQ":1},"inout":{}})
        self.assertAlmostEqual(x.targets["QQQ"],.8)
        self.assertAlmostEqual(x.cash_weight,.2)

    def test_cash_floor_and_negative_budget(self):
        with self.assertRaises(PortfolioError):
            combine({"beethoven":.99,"inout":.01},{"beethoven":{"QQQ":1},"inout":{}})
        with self.assertRaises(PortfolioError):
            combine({"beethoven":-.1},{"beethoven":{"QQQ":1}})

    def test_symbol_overlap_concentration_fails_rather_than_clips(self):
        with self.assertRaisesRegex(PortfolioError,"combined symbol cap"):
            combine({"beethoven":.6,"inout":.3},
                    {"beethoven":{"QQQ":1},"inout":{"QQQ":1}},
                    max_symbol_weight=.8)

    def test_invalid_weights_and_unknown_sleeve(self):
        for val in (-.1,float("nan"),float("inf"),1.1,True):
            with self.subTest(val=str(val)):
                with self.assertRaises(PortfolioError):
                    combine({"beethoven":.8},{"beethoven":{"QQQ":val}})
        with self.assertRaises(PortfolioError):
            combine({"beethoven":.8},{"other":{"QQQ":1}})
        with self.assertRaises(PortfolioError):
            combine({"beethoven":.8},{"beethoven":{"@@":1}})
        with self.assertRaises(PortfolioError):
            combine({"beethoven":.8},{"beethoven":{"QQQ":.8,"TLT":.8}})

    def test_disabled_sleeve_cannot_submit_positions(self):
        with self.assertRaisesRegex(PortfolioError,"Disabled"):
            combine({"beethoven":.8,"ema_vwap":0},
                    {"beethoven":{"QQQ":1},"ema_vwap":{"SPY":1}})

    def test_no_leverage_and_no_short_current_holdings(self):
        with self.assertRaises(PortfolioError):
            combine({"beethoven":.8},{"beethoven":{"QQQ":1}},
                    current_weights={"GLD":-0.01})
        with self.assertRaises(PortfolioError):
            combine({"beethoven":1.1},{"beethoven":{"QQQ":1}})

    def test_inout_needs_complete_252_sessions(self):
        f=self.history().iloc[:200]
        with self.assertRaisesRegex(ValueError,"252"):
            inout_from_closes(f)

    @staticmethod
    def history():
        ix=pd.bdate_range("2025-01-01",periods=254)
        cols=("QQQ","XLI","DBB","IGE","SHY","UUP","GLD","SLV","XLU","FXF","FXA")
        f=pd.DataFrame(index=ix)
        for i,k in enumerate(cols):
            f[k]=np.linspace(80+i,100+i,len(ix))
        return f

    def test_inout_shock_enters_defense(self):
        f=self.history()
        f.loc[f.index[-1],"DBB"]=f.loc[f.index[-1],"DBB"]*.3
        x=inout_from_closes(f)
        self.assertFalse(x.state.is_in)
        self.assertIn("DBB",x.triggered)
        self.assertEqual(x.weights,{"TLT":.4,"IEF":.4,"GLD":.2})
        with self.assertRaisesRegex(ValueError,"Cannot reuse"):
            inout_from_closes(f,x.state)

    def test_inout_recovers_after_15_nonshock_sessions(self):
        f=self.history()
        state=RegimeState(is_in=False,days_since_exit=13)
        # Synthetic smooth uptrend should produce no bottom 1% shocks
        z=inout_from_closes(f,state)
        self.assertFalse(z.state.is_in)
        f2=f.copy()
        f2.loc[f2.index[-1]+pd.offsets.BDay(1)]=f2.iloc[-1]*1.001
        w=inout_from_closes(f2,z.state)
        self.assertTrue(w.state.is_in)
        self.assertEqual(w.weights,{"QQQ":1.})

if __name__=="__main__":
    unittest.main()
