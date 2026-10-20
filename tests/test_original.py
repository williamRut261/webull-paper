import unittest
from unittest.mock import patch
from strategy_engine import original_targets, ORIGINAL_EXECUTION_ASSETS, load_strategy, walk
import flow_state_remote as bot

class OriginalTests(unittest.TestCase):
    def test_all_source_holdings_retained(self):
        for node in walk(load_strategy()):
            if node['step'] == 'asset':
                symbol = node['ticker']
                self.assertEqual(original_targets({symbol: 1.0}), {symbol: .99})
                bot.validate_targets({symbol: .99})

    def test_actual_bot_keeps_leveraged_inverse_and_volatility(self):
        raw = {'TQQQ': .4, 'GDXD': .3, 'UVXY': .3}
        with patch.object(bot, 'Evaluator') as cls, patch.object(bot, 'log'):
            cls.return_value.evaluate.return_value = raw
            self.assertEqual(bot.build_targets(None), original_targets(raw))

    def test_invalid_source_and_exposure_rejected(self):
        for raw in ({'UNKNOWN':1}, {'TQQQ':-.1,'QQQ':1.1}, {'TQQQ':float('nan')}, {'TQQQ':.5}):
            with self.assertRaises(ValueError): original_targets(raw)
        with self.assertRaises(ValueError): original_targets({'TQQQ':1},1.01)

if __name__ == '__main__': unittest.main()
