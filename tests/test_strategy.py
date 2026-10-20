import json
import math
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from strategy_engine import *


def asset(s, ident=None, **extra):
    return dict(id=ident or s, step='asset', ticker=s, **extra)


def node(step, children, **extra):
    return dict(id='parent', step=step, children=children, **extra)


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.root = load_strategy()
        self.closes = pd.DataFrame({'QQQ': [100, 110, 121], 'BIL': [100, 100.1, 100.2], 'TLT': [100, 90, 81]})

    def test_all_source_blocks_retained(self):
        from collections import Counter
        self.assertEqual(Counter(n['step'] for n in walk(self.root)), {
            'asset':177, 'if-child':134, 'wt-cash-equal':87, 'if':67,
            'group':20, 'filter':9, 'wt-cash-specified':5, 'root':1, 'wt-inverse-vol':1})
        self.assertEqual(self.root['id'], 'R9gMXtESOZq5kDU1lUvM')

    def test_every_leaf_maps_safely(self):
        for n in walk(self.root):
            if n['step'] == 'asset':
                t = compliant_targets({n['ticker']:1})
                self.assertAlmostEqual(sum(t.values()), .99)
                self.assertFalse(set(t) & BLOCKED_ASSETS)

    def test_merge_after_mapping_preserves_weights(self):
        self.assertEqual(compliant_targets({'TQQQ':.6, 'QLD':.2, 'SQQQ':.2}), {'QQQ':.792, 'BIL':.198})

    def test_no_inverse_to_bull_substitution(self):
        for s in ['GDXD','FAZ','PSQ','SOXS','SQQQ','SRTY','TECS','UVXY','WEBS','BTAL']:
            self.assertEqual(compliant_targets({s:1}), {'BIL':.99})

    def test_invalid_weights_and_unknown_symbols(self):
        for raw in [{'QQQ':float('nan')}, {'QQQ':-1}, {'QQQ':1.1}, {'UNKNOWN':1}]:
            with self.assertRaises(ValueError):compliant_targets(raw)

    def test_nested_specified_equal(self):
        branch = node('wt-cash-equal', [asset('QQQ'),asset('TLT')], weight={'num':60,'den':100})
        branch['id']='nested'
        root = node('wt-cash-specified', [branch,asset('BIL',weight={'num':40,'den':100})])
        self.assertEqual(Evaluator(root,self.closes).evaluate(), {'QQQ':.3,'TLT':.3,'BIL':.4})

    def test_rank_top_bottom_percent_returns(self):
        for direction, expected in [('top', {'QQQ':.5,'BIL':.5}),('bottom',{'TLT':.5,'BIL':.5})]:
            root=node('filter',[asset('QQQ'),asset('BIL'),asset('TLT')], **{'sort-by-fn':'moving-average-return','sort-by-fn-params':{'window':2},'select-fn':direction,'select-n':'2'})
            self.assertEqual(Evaluator(root,self.closes).evaluate(),expected)

    def test_resolve_nested_candidates_then_deduplicate(self):
        eq=node('wt-cash-equal',[asset('QQQ','q1'),asset('BIL','b1')]);eq['id']='eq'
        root=node('filter',[eq,asset('QQQ','q2')], **{'sort-by-fn':'cumulative-return','sort-by-window-days':'2','select-fn':'top','select-n':'2'})
        self.assertEqual(Evaluator(root,self.closes).evaluate(),{'QQQ':.5,'BIL':.5})

    def test_inverse_vol_and_zero_vol(self):
        root=node('wt-inverse-vol',[asset('BIL'),asset('TLT')], **{'window-days':'2'})
        ev=Evaluator(root,self.closes)
        with patch.object(ev,'metric',side_effect=[1.,3.]):
            self.assertEqual(ev.evaluate(),{'BIL':.75,'TLT':.25})
        with patch.object(ev,'metric',side_effect=[0.,3.]):
            self.assertEqual(ev.evaluate(),{'BIL':1.})

    def test_indicators_known_values(self):
        self.assertAlmostEqual(indicator([100,110,121],'cumulative-return',2),21.)
        self.assertAlmostEqual(indicator([100,110,121],'moving-average-return',2),10.)
        self.assertEqual(indicator([100,110,120],'moving-average-price',2),115.)
        self.assertEqual(indicator([1,2,3,4],'relative-strength-index',3),100.)
        self.assertEqual(indicator([4,3,2,1],'relative-strength-index',3),0.)
        self.assertEqual(indicator([4,4,4,4],'relative-strength-index',3),50.)
        self.assertAlmostEqual(indicator([100,102,101,103,102],'relative-strength-index',3),100-100/(1+(8/9)/(5/9)))
        self.assertAlmostEqual(indicator([100,110,99],'standard-deviation-return',2),math.sqrt(.02)*100)

    def test_missing_stale_gap_and_short_history_fail(self):
        for values in [[1,2], [1,float('nan'),3], [1,2,float('nan')], [1,0,3], [1,float('inf'),3]]:
            with self.assertRaises(ValueError):indicator(values,'cumulative-return',2)
        ev=Evaluator(self.root,pd.DataFrame({'GDXU':[1,2,float('nan')]}))
        with self.assertRaises(ValueError):ev.evaluate()

    def test_root_gdx_thresholds_and_signal_not_substitute(self):
        for rsi10,rsi3,expected in [(80,50,'GDXD'),(79,29,'GDXU')]:
            ev=Evaluator(self.root,self.closes)
            def metric(s,fn,d):
                self.assertEqual(s,'GDXU')
                return rsi10 if d==10 else rsi3
            with patch.object(ev,'metric',side_effect=metric):
                self.assertEqual(ev.evaluate(),{expected:1.})

    def test_every_conditional_arm_can_evaluate(self):
        # Evaluate each source conditional in isolation, forcing each immediate arm.
        # Its descendants still recurse through the complete original tree.
        for n in walk(self.root):
            if n['step']!='if':continue
            for selected in n['children']:
                ev=Evaluator(self.root,self.closes)
                with patch.object(ev,'condition',side_effect=lambda c: c['id']==selected['id']), patch.object(ev,'metric',return_value=12.):
                    raw=ev.evaluate(n)
                    self.assertAlmostEqual(sum(raw.values()),1)
                    self.assertAlmostEqual(sum(compliant_targets(raw).values()),.99)

    def test_all_filters_and_weight_blocks_evaluate(self):
        for n in walk(self.root):
            if n['step'] not in ('filter','wt-cash-specified','wt-inverse-vol'):continue
            ev=Evaluator(self.root,self.closes)
            with patch.object(ev,'condition',return_value=False),patch.object(ev,'metric',return_value=12.):
                self.assertAlmostEqual(sum(ev.evaluate(n).values()),1)

    def test_unsupported_node_rejected(self):
        with self.assertRaises(ValueError):Evaluator(node('unknown',[asset('QQQ')]),self.closes)

    def test_full_tree_with_synthetic_market_history(self):
        rng=np.random.default_rng(66)
        prices=pd.DataFrame({s:100*np.exp(np.cumsum(rng.normal(.0002,.012,1100))) for s in sorted(signal_symbols(self.root))})
        t=compliant_targets(Evaluator(self.root,prices).evaluate())
        self.assertAlmostEqual(sum(t.values()),.99)
        self.assertFalse(set(t)&BLOCKED_ASSETS)

class BacktestTests(unittest.TestCase):
    def test_lagged_signal_and_mapping_returns(self):
        from backtest import run
        root=asset('TQQQ')
        prices=pd.DataFrame({'TQQQ':[100.,200.,100.], 'QQQ':[100.,110.,99.]},index=pd.date_range('2025-01-01',periods=3))
        with patch('backtest.load_strategy',return_value=root):
            result=run(prices,'2025-01-01')
        self.assertAlmostEqual(result['original'].iloc[-1],1.)
        self.assertAlmostEqual(result['compliant'].iloc[-1],1.099*.901)

    def test_backtest_rejects_missing_execution_data(self):
        from backtest import run
        prices=pd.DataFrame({'TQQQ':[100.,200.]},index=pd.date_range('2025-01-01',periods=2))
        with patch('backtest.load_strategy',return_value=asset('TQQQ')):
            with self.assertRaises(ValueError):run(prices,'2025-01-01')

    def test_backtest_excludes_future_from_signal(self):
        from backtest import run
        prices=pd.DataFrame({'QQQ':[100.,110.,120.]},index=pd.date_range('2025-01-01',periods=3))
        seen=[]
        class SpyEvaluator:
            def __init__(self,root,history):seen.append(len(history))
            def evaluate(self):return {'QQQ':1.}
        with patch('backtest.Evaluator',SpyEvaluator):run(prices,'2025-01-01')
        self.assertEqual(seen,[1,2])

if __name__=='__main__':unittest.main()
