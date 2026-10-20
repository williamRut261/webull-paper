import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch,create_autospec
import pandas as pd
import flow_state_remote as bot
from alpaca.trading.enums import OrderSide


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches=[patch.object(bot,'STATE_DIR',Path(self.tmp.name)),patch.object(bot,'log'),patch.object(bot,'trading_client',create_autospec(bot.TradingClient, instance=True))]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        bot.trading_client.get_account.return_value=NS(equity='1000',cash='500',trading_blocked=False,account_blocked=False)
        bot.trading_client.get_all_positions.return_value=[]
        bot.trading_client.get_orders.return_value=[]
        bot.trading_client.get_clock.return_value=NS(is_open=True,next_close='later')
        bot.trading_client.submit_order.return_value=NS(id='order')
        bot.trading_client.get_order_by_id.return_value=NS(status='filled',symbol='QQQ',filled_qty='1',filled_avg_price='100')
        bot.trading_client.get_asset.return_value=NS(tradable=True,fractionable=True,status='active')

    def test_paper_client_hardlock(self):
        with patch.dict('os.environ',{'ALPACA_API_KEY':'dummy','ALPACA_SECRET_KEY':'dummy'}),patch.object(bot,'TradingClient') as cls,patch.object(bot,'StockHistoricalDataClient'):
            bot.connect();cls.assert_called_once_with('dummy','dummy',paper=True)
        with patch.object(bot,'PAPER',False):
            with self.assertRaises(RuntimeError):bot.connect()

    def test_bad_target_numbers_block(self):
        for t in [{'QQQ':float('nan')},{'QQQ':float('inf')},{'QQQ':-.1},{'QQQ':1.01},{'UNREVIEWED':.99},{}]:
            with self.assertRaises(RuntimeError):bot.validate_targets(t)

    def test_cash_capped_dollar_order(self):
        bot.submit_market_order('QQQ',OrderSide.BUY,bot.today_tag(),notional=900)
        req=bot.trading_client.submit_order.call_args.kwargs['order_data']
        self.assertEqual(req.notional,497.5);self.assertIsNone(req.qty)
        self.assertTrue(req.client_order_id.startswith('flowstate-'+bot.today_tag()))

    def test_all_positions_count_for_gross_limit(self):
        bot.trading_client.get_all_positions.return_value=[NS(symbol='UNMANAGED',qty='1',market_value='985',side='long')]
        bot.submit_market_order('QQQ',OrderSide.BUY,bot.today_tag(),notional=400)
        bot.trading_client.submit_order.assert_not_called()

    def test_gross_headroom_caps_buy(self):
        bot.trading_client.get_all_positions.return_value=[NS(symbol='SPY',qty='1',market_value='950',side='long')]
        bot.submit_market_order('QQQ',OrderSide.BUY,bot.today_tag(),notional=400)
        self.assertEqual(bot.trading_client.submit_order.call_args.kwargs['order_data'].notional,40.)

    def test_sell_cannot_exceed_owned_shares(self):
        bot.trading_client.get_all_positions.return_value=[NS(symbol='QQQ',qty='1.123456789',market_value='100',side='long')]
        bot.submit_market_order('QQQ',OrderSide.SELL,bot.today_tag(),qty=5)
        self.assertEqual(bot.trading_client.submit_order.call_args.kwargs['order_data'].qty,1.123456)

    def test_short_negative_cash_nan_account_block(self):
        bot.trading_client.get_all_positions.return_value=[NS(symbol='QQQ',qty='-1',market_value='-100')]
        with self.assertRaises(RuntimeError):bot.get_positions()
        for cash in ['-1','nan','inf']:
            bot.trading_client.get_account.return_value.cash=cash
            with self.assertRaises(RuntimeError):bot.get_account()

    def test_market_open_orders_and_date_rechecked(self):
        bot.trading_client.get_clock.return_value.is_open=False
        with self.assertRaises(RuntimeError):bot.submit_market_order('QQQ',OrderSide.BUY,bot.today_tag(),notional=50)
        bot.trading_client.get_clock.return_value.is_open=True
        bot.trading_client.get_orders.return_value=[NS(id='pending')]
        with self.assertRaises(RuntimeError):bot.submit_market_order('QQQ',OrderSide.BUY,bot.today_tag(),notional=50)
        with self.assertRaises(RuntimeError):bot.submit_market_order('QQQ',OrderSide.BUY,'19000101',notional=50)
        bot.trading_client.submit_order.assert_not_called()

    def test_broker_duplicate_history_and_truncation(self):
        bot.trading_client.get_orders.return_value=[NS(client_order_id='flowstate-'+bot.today_tag()+'-buy-QQQ')]
        self.assertTrue(bot.already_ran_today())
        bot.trading_client.get_orders.return_value=[NS(client_order_id='other')]*500
        with self.assertRaises(RuntimeError):bot.already_ran_today()

    def test_same_day_claim_even_without_orders(self):
        bot.claim_day(bot.today_tag())
        with self.assertRaises(FileExistsError):bot.claim_day(bot.today_tag())

    def test_rejected_partial_and_timeout_stop(self):
        bot.trading_client.get_order_by_id.return_value.status='rejected'
        with self.assertRaises(RuntimeError):bot.wait_for_order('order')
        bot.trading_client.get_order_by_id.return_value.status='partially_filled'
        with patch.object(bot,'ORDER_FILL_TIMEOUT',0):
            with self.assertRaises(RuntimeError):bot.wait_for_order('order')

    def test_nonfractionable_asset_fails_before_order(self):
        bot.trading_client.get_asset.return_value.fractionable=False
        with self.assertRaises(RuntimeError):bot.rebalance({'QQQ':.99},bot.today_tag())
        bot.trading_client.submit_order.assert_not_called()

    def test_failed_sale_never_buys(self):
        bot.trading_client.get_all_positions.return_value=[NS(symbol='TLT',qty='5',market_value='500',side='long')]
        bot.trading_client.get_order_by_id.return_value.status='rejected'
        with self.assertRaises(RuntimeError):bot.rebalance({'QQQ':.99},bot.today_tag())
        self.assertEqual(bot.trading_client.submit_order.call_count,1)
        self.assertEqual(bot.trading_client.submit_order.call_args.kwargs['order_data'].side,OrderSide.SELL)

    def test_default_dry_run_and_duplicate_main(self):
        with patch.object(bot,'connect'),patch.object(bot,'get_price_data',return_value=pd.DataFrame()),patch.object(bot,'build_targets',return_value={'QQQ':.99}),patch.object(bot,'rebalance') as reb:
            self.assertEqual(bot.main([]),0);reb.assert_not_called()
            bot.claim_day(bot.today_tag())
            self.assertEqual(bot.main(['--paper-execute']),0);reb.assert_not_called()

    def test_offline_execution_prohibited(self):
        with self.assertRaises(SystemExit):bot.main(['--paper-execute','--prices-csv','fake.csv'])

    def test_completed_adjusted_sessions_and_missing_bar(self):
        days=pd.date_range('2025-01-02',periods=3,freq='B')
        bot.trading_client.get_calendar.return_value=[NS(date=d) for d in days]
        index=pd.MultiIndex.from_product([['QQQ'],days[:2].tz_localize('America/New_York')],names=['symbol','timestamp'])
        data=Mock();data.get_stock_bars.return_value=NS(df=pd.DataFrame({'close':[100.,101.]},index=index))
        with patch.object(bot,'data_client',data):
            closes=bot.get_price_data({'QQQ'})
        self.assertTrue(pd.isna(closes['QQQ'].iloc[-1]))
        request=data.get_stock_bars.call_args.args[0]
        self.assertEqual(request.adjustment.value,'all')
        self.assertEqual(request.end.replace(tzinfo=bot.timezone.utc).astimezone(bot.MARKET_TZ).hour,0)

if __name__=='__main__':unittest.main()
