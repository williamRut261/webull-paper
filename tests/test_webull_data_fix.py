"""Offline data-path regressions. No credentials, network or diagnostic orders."""
import contextlib
import hashlib
import io
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pandas as pd
from strategy_engine import load_strategy, signal_symbols, walk
from webull_paper import paper_orders as paper, automatic as bot
from webull_paper.signal_dry_run import assemble_history, unwrap_bars
from webull_paper.audit_quotes import quote_time


def ok(payload):
    return NS(status_code=200, json=lambda: payload)


class DataFixTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 15, 48, 1, tzinfo=paper.NY)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def row(self, symbol, stamp=None):
        stamp = stamp or self.now
        return dict(symbol=symbol, price=150., pre_close=149.,
                    last_trade_time=int(stamp.timestamp()*1000))

    def fixture(self):
        root = load_strategy()
        symbols = sorted(signal_symbols(root))
        dates = paper.completed_sessions(pd.Timestamp('2026-07-01'), self.now.date())[-50:]
        history = pd.DataFrame({s: range(100, 150) for s in symbols}, index=dates, dtype=float)
        rows = {s: self.row(s) for s in symbols}
        data = Mock()
        data.market_data.get_snapshot.side_effect = lambda symbols, category: ok(
            [rows[s] for s in symbols if s in rows])
        return root, history, rows, data

    def evaluate(self, root, history, data, observed=None):
        with patch.object(paper, 'assemble_history', return_value=history):
            return paper.targets_for_now(data, root, self.now, True,
                                         clock=lambda: observed or self.now)

    def test_trade_during_requests_is_not_future_relative_to_receipt(self):
        data = Mock()
        row = self.row('SPY', self.now + timedelta(seconds=4))
        data.market_data.get_snapshot.return_value = ok([row])
        prices, _ = paper.collect_snapshots(data, ['SPY'], self.now, clock=lambda: self.now+timedelta(seconds=7))
        self.assertEqual(prices['SPY'], 150.)
        # The old reference time would reject this otherwise valid trade.
        with self.assertRaisesRegex(RuntimeError, 'future'):
            paper.collect_snapshots(data, ['SPY'], self.now)

    def test_clock_is_read_after_last_response(self):
        events = []
        data = Mock()
        def fetch(symbols, category):
            events.append('fetch')
            return ok([self.row(s) for s in symbols])
        data.market_data.get_snapshot.side_effect = fetch
        def clock():
            events.append('clock')
            return self.now
        paper.collect_snapshots(data, [str(i) for i in range(11)], self.now, clock=clock)
        self.assertEqual(events, ['fetch', 'fetch', 'clock'])

    def test_timestamp_formats_and_bad_values(self):
        data = Mock()
        for value in [int(self.now.timestamp()*1000), str(int(self.now.timestamp()*1000)), self.now.isoformat()]:
            row = self.row('SPY'); row['last_trade_time'] = value
            data.market_data.get_snapshot.return_value = ok([row])
            self.assertEqual(paper.collect_snapshots(data, ['SPY'], self.now)[0]['SPY'], 150.)
        for value in [None, True, float('nan'), float('inf'), 'bad', '2026-10-15T15:48:01']:
            with self.subTest(value=value), self.assertRaises((ValueError, OverflowError)):
                quote_time(value)

    def test_age_limit_boundary_future_and_other_session(self):
        data = Mock()
        for seconds, reason in [(1200, None), (1201, 'stale_over_20m'), (-1, 'future_timestamp'), (86400, 'other_session')]:
            data.market_data.get_snapshot.return_value = ok([self.row('SPY', self.now-timedelta(seconds=seconds))])
            prices, _ = paper.collect_snapshots(data, ['SPY'], self.now, allow_unused_stale=True)
            self.assertEqual('SPY' in prices, reason is None)
            if reason:
                self.assertIn(reason, self.output.getvalue())

    def test_active_missing_quote_names_dependency_and_does_not_use_old_close(self):
        root, history, rows, data = self.fixture()
        del rows['GDXU']
        with self.assertRaisesRegex(ValueError, 'REQUIRED GDXU relative-strength-index'):
            self.evaluate(root, history, data)
        self.assertIn('2026-10-15', self.output.getvalue())

    def test_unused_missing_history_and_snapshot_do_not_block(self):
        root, history, rows, data = self.fixture()
        history['AGQ'] = float('nan')
        del rows['AGQ']
        targets, quotes = self.evaluate(root, history, data)
        self.assertEqual(targets, {'GDXD': .99})
        self.assertNotIn('AGQ', quotes.required)
        self.assertEqual(quotes.required, {'GDXU', 'GDXD'})

    def test_unused_missing_prior_adjustment_does_not_abort(self):
        root, history, rows, data = self.fixture()
        history.loc[history.index[-1], 'AGQ'] = float('nan')
        self.assertEqual(self.evaluate(root, history, data)[0], {'GDXD': .99})

    def test_internal_gap_and_missing_prior_session_fail_closed(self):
        for mode in ['internal', 'prior_all']:
            root, history, rows, data = self.fixture()
            if mode == 'internal':
                history.loc[history.index[-4], 'GDXU'] = float('nan')
            else:
                history = history.iloc[:-1]
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'REQUIRED GDXU'):
                self.evaluate(root, history, data)

    def test_ranking_branch_needs_all_candidate_metrics(self):
        root, history, rows, data = self.fixture()
        root = next(n for n in walk(root) if n['id'] == 'd3f14fa5-41cc-4117-860d-5f7d5247974c')
        del rows['AGQ']
        with self.assertRaisesRegex(ValueError, 'REQUIRED AGQ'):
            self.evaluate(root, history, data)

    def test_fetch_crossing_cutoff_aborts_before_evaluation(self):
        root, history, rows, data = self.fixture()
        with self.assertRaisesRegex(RuntimeError, 'restricted'):
            self.evaluate(root, history, data, self.now.replace(minute=55))

    def test_holiday_early_close_and_naive_time_rejected(self):
        for now in [datetime(2026, 12, 25, 15, 49, tzinfo=paper.NY),
                    datetime(2026, 11, 27, 15, 49, tzinfo=paper.NY),
                    datetime(2026, 10, 15, 15, 49)]:
            with self.subTest(now=now), self.assertRaises(RuntimeError):
                paper.session_guard(now)
        paper.session_guard(self.now)
        paper.session_guard(self.now.astimezone(__import__('datetime').timezone.utc))

    def test_expired_signal_or_missing_sale_quote_blocks_all_orders(self):
        root, history, rows, data = self.fixture()
        _, quotes = self.evaluate(root, history, data)
        quotes.trade_times['GDXU'] = self.now-timedelta(minutes=19, seconds=59)
        for held, now in [({}, self.now+timedelta(seconds=2)),
                          ({'AGQ': {'qty': 1., 'value': 100., 'price': 100.}}, self.now)]:
            quotes.pop('AGQ', None)
            with patch.object(bot, 'checked_portfolio', return_value=(5000., 4900., held)), \
                 patch.object(bot, 'datetime') as clock, \
                 patch.object(bot, 'preview_and_place') as submit:
                clock.now.return_value = now
                with self.assertRaises(RuntimeError):
                    bot.make_orders(Mock(), 'sandbox', {'GDXD': .99}, quotes, '2026-10-15')
                submit.assert_not_called()

    def test_preview_latency_revalidates_before_placement(self):
        trade = Mock()
        trade.order_v3.preview_order.return_value = ok({'ok': True})
        guard = Mock(side_effect=[None, RuntimeError('quote expired')])
        with patch.object(bot, 'datetime') as clock:
            clock.now.return_value = self.now
            with self.assertRaisesRegex(RuntimeError, 'quote expired'):
                bot.preview_and_place(trade, 'sandbox', {'client_order_id': 'test'}, before_submit=guard)
        trade.order_v3.place_order.assert_not_called()

    def test_missing_history_symbol_is_only_optional_for_branch_evaluation(self):
        dates = paper.completed_sessions(pd.Timestamp('2026-07-01'), self.now.date())[-50:]
        payload = [{'symbol': 'GDXU', 'result': [
            {'time': d.tz_localize(paper.NY).isoformat(), 'close': 100.} for d in dates]}]
        data = Mock()
        data.market_data.get_batch_history_bar.return_value = ok(payload)
        frame = assemble_history(data, ['AGQ', 'GDXU'], self.now.date(), allow_missing=True)
        self.assertTrue(frame.AGQ.isna().all())
        with self.assertRaisesRegex(RuntimeError, 'missing required tickers'):
            assemble_history(data, ['AGQ', 'GDXU'], self.now.date())
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            unwrap_bars(payload+payload)

    def test_source_tree_and_evaluator_unchanged(self):
        self.assertEqual(len(list(walk(load_strategy()))), 501)
        self.assertTrue(Path('strategy/paper_strategy.json').is_file())
        import json
        audit = json.loads(Path('strategy/source_audit.json').read_text())
        self.assertEqual(audit['node_count'], 501)
        self.assertEqual(audit['node_counts']['asset'], 177)
