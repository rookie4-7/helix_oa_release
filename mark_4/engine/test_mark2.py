from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

import runtime
from config import Mark4Params, read_strategy_params, validate_params
from entry_exit_logic import entry_price_from_range
from market_sessions import to_london
from pivot_logic import PivotBook, pivot_confirmations, historical_breaks
from setup_logic import BreakFlags
from strategy_logic import generate_signals
from workbook_config import WorkbookConfigError


def row(t, op, close):
    hi, lo = max(op, close), min(op, close)
    return dict(time=t, london_time=to_london(t), london_date=to_london(t).date(),
        mid_open=op, mid_close=close, mid_high=hi+.0001, mid_low=lo-.0001,
        buy_body_high=hi, sell_body_high=hi, buy_body_low=lo, sell_body_low=lo,
        buy_body_size=hi-lo, sell_body_size=hi-lo, direction=(close>op)-(close<op))


def fixture():
    base=datetime(2022,1,5)
    data=[row(base+timedelta(minutes=15*i),o,c) for i,(o,c) in enumerate([
        (1.3,1.3001),(1.3001,1.3002),(1.3002,1.3005),(1.3003,1.3002),(1.3002,1.3001)])]
    data.extend([row(base.replace(hour=7,minute=45),1.3002,1.3001),
                 row(base.replace(hour=8),1.3001,1.3010),
                 row(base.replace(hour=8,minute=15),1.301,1.3008),
                 row(base.replace(hour=8,minute=30),1.3008,1.3006)])
    return data


def params():
    return replace(Mark4Params(),use_trendline_obstacles=False,
                   use_asia_buy_setup=False,use_asia_sell_setup=False,
                   use_repeated_visit_pivot_exception=False,
                   use_pivot_obstacles=False,use_active_price_cluster_stop_filter=False,
                   reject_22_only_setups=False,
                   use_internal_structure_buy_setup=False,use_internal_structure_sell_setup=False,
                   use_buy_b_setup=False,use_sell_b_setup=False,
                   use_news_filter=False,use_news_forced_close=False)


class Rules(unittest.TestCase):
    def test_current_day_pivot_creates_setup(self):
        signals=generate_signals(fixture(),params())
        self.assertEqual(len(signals),1)
        self.assertEqual(signals[0]['setup_type'],'DS')
        self.assertEqual(signals[0]['status'],'Valid')
        self.assertAlmostEqual(signals[0]['entry'],1.301-(1.301-1.3001)*.618)
        self.assertTrue(signals[0]['entry_line_events'][0]['mark2_current_day_break_times'])

    def test_confirmation_only_after_right_candles_close(self):
        data=fixture()[:5]
        events=pivot_confirmations(data,(2,3,5))
        self.assertNotIn(3,events)
        self.assertTrue(any(p['formed_i']==2 and p['side']=='Buy' for p in events[4]))
        self.assertEqual(pivot_confirmations(data[:4],(2,3,5)),{})

    def test_scale_dedup_does_not_rearm_consumed_pivot(self):
        book=PivotBook(1024)
        p=dict(id='x',side='Buy',level=1.3,formed_i=0,confirmed_i=2,scale=2)
        book.confirm([p],2); book.records['x']['consumed']=True
        self.assertEqual(book.confirm([p|{'scale':3,'confirmed_i':3}],3),[])
        self.assertTrue(book.records['x']['consumed'])
        self.assertEqual(book.records['x']['scales'],{2,3})

    def test_equal_body_levels_qualify(self):
        data=[row(datetime(2022,1,5)+timedelta(minutes=15*i),1.3,1.3001) for i in range(5)]
        self.assertEqual(len(pivot_confirmations(data,(2,))[4]),2)

    def test_historical_only_never_creates_setup(self):
        with patch('strategy_logic.daily_swing_break_flags',return_value=BreakFlags(False,False,False,False)):
            self.assertEqual(generate_signals(fixture(),params()),[])

    def test_same_run_gate_and_simultaneous_break(self):
        r=fixture()[6]; p={'day':datetime(2022,1,4).date(),'side':'Buy'}
        self.assertEqual(historical_breaks([p],r,False,None),([],[p]))
        self.assertEqual(historical_breaks([p],r,True,None),([p],[]))
        run={'direction':1,'mark2_current_day_pivot_break':True}
        self.assertEqual(historical_breaks([p],r,False,run),([p],[]))
        self.assertEqual(historical_breaks([p],r,False,run,same_run=False),([],[p]))
        self.assertEqual(historical_breaks([p],r,False,run|{'direction':-1}),([],[p]))

    def test_age_limit(self):
        b=PivotBook(10); p={'id':'x','formed_i':0,'scale':2}
        b.confirm([p],2); b.confirm([],10); self.assertIn('x',b.records)
        b.confirm([],11); self.assertNotIn('x',b.records)

    def test_once_consumed_no_recross(self):
        b=PivotBook(1024); p=dict(id='x',side='Buy',level=1.3005,formed_i=0,confirmed_i=2,scale=2)
        b.confirm([p],2); data=fixture()
        self.assertEqual(len(b.cross(data[6],data[5],.00001,6)),1)
        self.assertEqual(b.cross(data[6],data[5],.00001,7),[])

    def test_removed_consolidation_cannot_be_enabled(self):
        for name in ['use_consolidation_buy_setup','use_consolidation_sell_setup','use_consolidation_obstacles']:
            with self.assertRaises(WorkbookConfigError):validate_params(replace(params(),**{name:True}))

    def test_all_setups_off_has_no_hidden_range_signals(self):
        p=replace(params(),use_daily_swing_buy_setup=False,use_daily_swing_sell_setup=False)
        self.assertEqual(generate_signals(fixture(),p),[])

    def test_small_setup_body_invalid(self):
        self.assertEqual(generate_signals(fixture(),replace(params(),min_imbalance_pips=20))[0]['status'],'Invalid')

    def test_six_candle_run_cannot_start_a_new_live_line(self):
        data=fixture()[:5]
        for i in range(6):
            op=1.299+i*.0002
            close=op+.0002 if i<5 else 1.301
            data.append(row(datetime(2022,1,5,6,45)+timedelta(minutes=15*i),op,close))
        data.append(row(datetime(2022,1,5,8,15),1.301,1.3009))
        self.assertEqual(generate_signals(data,params())[0]['status'],'Invalid')
        self.assertEqual(generate_signals(data,replace(params(),max_imbalance_candles=6))[0]['status'],'Valid')

    def test_consolidation_detector_is_absent(self):
        import setup_logic
        self.assertFalse(hasattr(setup_logic,'consolidation_snapshot'))
        self.assertFalse(hasattr(setup_logic,'consolidation_break_flags'))

    def test_break_distance_is_point_one_not_two(self):
        data=fixture(); data[6]=row(data[6]['time'],1.3001,1.30055)
        self.assertEqual(generate_signals(data,params())[0]['status'],'Valid')
        self.assertEqual(generate_signals(data,replace(params(),setup_break_pips=2)),[])

    def test_no_future_suffix_changes_earlier_lines(self):
        data=fixture()
        a=generate_signals(data,params())[0]['entry_line_events']
        more=[row(datetime(2022,1,5,9)+timedelta(minutes=i*15),1.4,1.5) for i in range(6)]
        b=generate_signals(data+more,params())[0]['entry_line_events']
        self.assertEqual(a,b)

    def test_london_dst(self):
        self.assertEqual(to_london(datetime(2022,3,28,7)).hour,8)
        self.assertEqual(to_london(datetime(2022,1,5,8)).hour,8)

    def test_multiple_trade_default(self):
        p=Mark4Params()
        self.assertFalse(p.only_first_filled_trade_per_day)
        self.assertFalse(p.block_same_direction_after_first_trade_per_day)

    def test_retracement_both_sides(self):
        self.assertAlmostEqual(entry_price_from_range(1.303,1.3,'Buy',.618),1.301146)
        self.assertAlmostEqual(entry_price_from_range(1.303,1.3,'Sell',.618),1.301854)


if __name__=='__main__': unittest.main()
