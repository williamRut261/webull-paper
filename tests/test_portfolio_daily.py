"""Research-only 25% x four daily performance ledger safety and accounting."""
import unittest
from research.portfolio_lab.daily import fresh,append,markdown,DailyLedgerError,SLEEVES


def sample(day="2026-10-21", returns=(.02,-.01,.005,0.0),mode="paper"):
    return {"date":day,"mode":mode,"strategies":{
        name:{"net_return":r,"evidence":"research-record://"+name+"/"+day,
              "signal_as_of":("2026-10-20" if day=="2026-10-21" else "2026-10-21"),
              "timing":"prior_close"} for name,r in zip(SLEEVES,returns)}}


class DailyPerformanceTests(unittest.TestCase):
    def test_four_25pct_sleeves_and_equal_daily_weights(self):
        a=fresh(10000)
        self.assertEqual(a["initial_sleeve_capital"],2500)
        b,row=append(a,sample())
        self.assertAlmostEqual(row["equal_weight_portfolio_daily_return_pct"],.375)
        self.assertAlmostEqual(row["equal_weight_portfolio_daily_pnl"],37.5)
        self.assertAlmostEqual(row["equal_weight_rebalanced_portfolio_equity"],10037.5)
        self.assertAlmostEqual(row["strategies"]["beethoven"]["independent_equity"],2550)
        self.assertEqual(row["ranking_by_daily_return"][0],"beethoven")
        self.assertEqual(a["entries"],[])

    def test_separate_compound_vs_daily_rebalanced_combined(self):
        a,_=append(fresh(),sample())
        b,row=append(a,sample(day="2026-10-22",returns=(-.01,.01,0.00,.02)))
        expected=10037.5*(1+(-.01+.01+0+.02)/4)
        self.assertAlmostEqual(b["equal_weight_rebalanced_portfolio_equity"],expected)
        self.assertAlmostEqual(b["independent_sleeve_equity"]["beethoven"],2550*.99)
        self.assertNotAlmostEqual(sum(b["independent_sleeve_equity"].values()),expected)
        self.assertEqual(len(b["entries"]),2)

    def test_reject_missing_sources_and_missing_strategy_without_zero(self):
        original=sample()
        for name in ("inout","rsi_trend"):
            obs=sample();del obs["strategies"][name]
            with self.assertRaises(DailyLedgerError):
                append(fresh(),obs)
        for source in ("", "example", "unknown", "REPLACE_WITH_VERIFIED_SOURCE", None):
            obs=sample();obs["strategies"]["inout"]["evidence"]=source
            with self.assertRaises(DailyLedgerError):
                append(fresh(),obs)
        self.assertEqual(len(original["strategies"]),4)

    def test_reject_mode_switch_duplicate_and_wrong_order(self):
        ledger,_=append(fresh(mode="paper"),sample())
        with self.assertRaisesRegex(DailyLedgerError,"Duplicate"):
            append(ledger,sample())
        with self.assertRaisesRegex(DailyLedgerError,"mix"):
            append(ledger,sample(day="2026-10-22",mode="backtest"))

    def test_reject_future_and_same_day_daily_close_and_bad_intraday(self):
        obs=sample();obs["strategies"]["beethoven"]["signal_as_of"]="2026-10-22"
        with self.assertRaises(DailyLedgerError): append(fresh(),obs)
        obs=sample();obs["strategies"]["beethoven"]["signal_as_of"]="2026-10-21"
        with self.assertRaises(DailyLedgerError): append(fresh(),obs)
        obs=sample();obs["strategies"]["claude_orb"]["timing"]="intraday"
        obs["strategies"]["claude_orb"]["signal_as_of"]="2026-10-20"
        with self.assertRaises(DailyLedgerError): append(fresh(),obs)

    def test_allow_same_day_intraday_claude_observation(self):
        obs=sample()
        obs["strategies"]["claude_orb"].update(signal_as_of="2026-10-21",timing="intraday")
        a,row=append(fresh(),obs)
        self.assertEqual(row["strategies"]["claude_orb"]["timing"],"intraday")

    def test_extreme_negative_and_nonfinite_returns_rejected(self):
        for val in (-1.001,float("nan"),float("inf"),None,True):
            obs=sample();obs["strategies"]["beethoven"]["net_return"]=val
            with self.subTest(val=str(val)):
                with self.assertRaises(DailyLedgerError): append(fresh(),obs)
        obs=sample(returns=(-1.0,0,0,0))
        a,row=append(fresh(),obs)
        self.assertEqual(row["strategies"]["beethoven"]["independent_equity"],0)

    def test_report_is_nonmisleading_and_contains_all_four(self):
        a,row=append(fresh(mode="backtest"),sample(mode="backtest"))
        report=markdown(row,a["mode"])
        for phrase in ("Beethoven","RSI Trend","Claude ORB",
                       "In & Out","daily","Evidence","25%","BACKTEST"):
            self.assertIn(phrase,report)

    def test_no_broker_sdk_or_live_operation_in_module(self):
        from research.portfolio_lab import daily
        self.assertFalse(hasattr(daily,"place_order"))
        self.assertFalse(hasattr(daily,"execute_trade"))


if __name__=="__main__": unittest.main()
