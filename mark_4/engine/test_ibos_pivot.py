from dataclasses import replace
from datetime import datetime
import unittest
from unittest.mock import patch

from pivot_logic import apply_ibos_pivot_requirement
from setup_logic import BreakFlags
from strategy_logic import generate_signals
from test_mark2 import fixture, params, row


def ibos_params():
    return replace(params(), use_daily_swing_buy_setup=False, use_daily_swing_sell_setup=False,
                   use_internal_structure_buy_setup=True, use_internal_structure_sell_setup=True,
                   use_internal_structure_asia_move_filter=False)


def raw_at(*times):
    def flags(**kw):
        r = kw['rows'][kw['idx']]
        active = r['time'].strftime('%H:%M') in times
        buy = active and r['direction'] == 1
        sell = active and r['direction'] == -1
        return BreakFlags(buy, sell, buy, sell)
    return flags


class IBOSPivotIntegration(unittest.TestCase):
    def signals(self, data, *times, **overrides):
        with patch('strategy_logic.internal_structure_break_flags', side_effect=raw_at(*times)):
            return generate_signals(data, replace(ibos_params(), **overrides))

    def test_same_candle_anchor_buy_and_sell(self):
        for direction in (1, -1):
            data = fixture()
            if direction == -1:
                data = [row(r['time'], 2.6-r['mid_open'], 2.6-r['mid_close']) for r in data]
            signal = self.signals(data, '08:00')[0]
            self.assertEqual(signal['status'], 'Valid')
            self.assertEqual(signal['setup_type'], 'IBOS')
            self.assertTrue(signal['ibos_pivot_requirement_met'])
            self.assertTrue(signal['entry_line_events'][0]['ibos_current_day_pivot_breaks'])

    def test_local_pivot_is_not_required_to_be_daily_extreme(self):
        with patch('strategy_logic.daily_swing_break_flags', return_value=BreakFlags(False,False,False,False)):
            self.assertEqual(self.signals(fixture(), '08:00')[0]['status'], 'Valid')

    def test_candidate_without_pivot_is_diagnostic_only(self):
        with patch('strategy_logic.pivot_confirmations', return_value={}):
            signal = self.signals(fixture(), '08:00')[0]
        self.assertEqual(signal['status'], 'Invalid')
        self.assertEqual(signal['entry_line_events'], [])
        self.assertIn('current-day pivot break', signal['reason'])

    def test_wick_only_crossing_does_not_qualify(self):
        data = fixture()
        data[6] = row(data[6]['time'], 1.2999, 1.30049)
        data[6]['mid_high'] = 1.3015
        self.assertEqual(self.signals(data, '08:00')[0]['status'], 'Invalid')

    def test_later_pivot_in_run_never_backdates_live_entry(self):
        data = fixture()
        data[6] = row(data[6]['time'], 1.2999, 1.30045)
        data[7] = row(data[7]['time'], 1.30045, 1.3009)
        signal = self.signals(data, '08:00')[0]
        self.assertEqual(signal['status'], 'Valid')
        self.assertEqual(signal['signal_time'], datetime(2022,1,5,8,15))
        self.assertEqual(signal['execution_start_time'], datetime(2022,1,5,8,30))
        self.assertEqual(signal['run_count'], 2)
        prefix = self.signals(data[:7], '08:00')[0]
        self.assertEqual(prefix['entry_line_events'], [])

    def test_pivot_before_ibos_in_same_run(self):
        data = fixture()
        data[7] = row(data[7]['time'], 1.3010, 1.3016)
        signal = self.signals(data, '08:15')[0]
        self.assertEqual(signal['status'], 'Valid')
        self.assertEqual(signal['signal_time'], datetime(2022,1,5,8,15))
        self.assertEqual(signal['ibos_current_day_pivot_breaks'][0]['break_time'], datetime(2022,1,5,8))

    def test_anchor_in_previous_run_does_not_qualify(self):
        data = fixture()
        data[8] = row(data[8]['time'], 1.3008, 1.3014)
        signal = self.signals(data, '08:30')[0]
        self.assertEqual(signal['status'], 'Invalid')

    def test_pre_london_consumed_break_cannot_anchor_london_run(self):
        data = fixture()
        data[5] = row(data[5]['time'], 1.3001, 1.3008)
        data[6] = row(data[6]['time'], 1.3008, 1.3014)
        self.assertEqual(self.signals(data, '08:00')[0]['status'], 'Invalid')

    def test_other_setup_is_not_blocked_by_ibos_gate(self):
        with patch('strategy_logic.pivot_confirmations', return_value={}):
            signal = self.signals(fixture(), '08:00', use_asia_buy_setup=True)[0]
        self.assertEqual(signal['status'], 'Valid')
        self.assertEqual(signal['setup_type'], 'A')
        self.assertFalse(signal['ibos_pivot_requirement_met'])

    def test_small_ibos_candle_not_rescued_by_later_large_pivot_break(self):
        data = fixture()
        data[6] = row(data[6]['time'], 1.3001, 1.3003)
        data[7] = row(data[7]['time'], 1.3003, 1.3015)
        self.assertEqual(self.signals(data, '08:00')[0]['status'], 'Invalid')

    def test_entry_touch_freeze_does_not_transfer_anchor_to_new_run(self):
        data = fixture()
        data[7] = row(data[7]['time'], 1.3010, 1.3018)
        data[7]['mid_low'] = 1.3003
        execution = [row(datetime(2022,1,5,8,16), 1.3005, 1.3004)]
        with patch('strategy_logic.internal_structure_break_flags', side_effect=raw_at('08:15')):
            signals = generate_signals(data, replace(ibos_params(), use_asia_buy_setup=True), execution_rows=execution)
        self.assertEqual(len(signals), 2)
        self.assertTrue(signals[0]['extension_freeze'])
        self.assertEqual(signals[0]['status'], 'Valid')
        self.assertEqual(signals[1]['status'], 'Invalid')
        self.assertEqual(signals[1]['ibos_current_day_pivot_breaks'], [])


class IBOSPivotGate(unittest.TestCase):
    def setUp(self):
        self.row = fixture()[6]
        self.pivot = dict(id='x', side='Buy', level=1.3005, day=self.row['london_date'],
                          formed_i=2, confirmed_i=4, formed_time=fixture()[2]['time'], scales={2})

    def gate(self, pivots, candidate=True, inside=True, base=None):
        run = dict(internal=False, has_setup=False, internal_valid=False, valid_imbalance=False,
                   largest_body_pips=0, first_setup_i=None, first_valid_i=None)
        run.update(base or {})
        apply_ibos_pivot_requirement(run, self.row, 6, 6, pivots, inside, candidate, True, 9)
        return run

    def test_prior_day_wrong_side_and_unconfirmed_are_excluded(self):
        for change in ({'day': datetime(2022,1,4).date()}, {'side':'Sell'}, {'confirmed_i':6}, {'confirmed_i':7}):
            self.assertFalse(self.gate([self.pivot | change])['internal'])

    def test_pivot_alone_cannot_create_ibos(self):
        self.assertFalse(self.gate([self.pivot], candidate=False)['has_setup'])

    def test_outside_london_cannot_activate(self):
        self.assertFalse(self.gate([self.pivot], inside=False)['has_setup'])

    def test_unanchored_ibos_cannot_supply_valid_body_to_other_setup(self):
        result = self.gate([], base={'has_setup':True, 'asia':True, 'asia_valid':False})
        self.assertFalse(result['valid_imbalance'])

    def test_existing_other_setup_remains_valid(self):
        result = self.gate([], base={'has_setup':True, 'valid_imbalance':True, 'first_valid_i':5})
        self.assertTrue(result['valid_imbalance'])
        self.assertEqual(result['first_valid_i'], 5)

    def test_gate_audit_does_not_change_with_later_confirmation_scale(self):
        result = self.gate([self.pivot])
        self.pivot['scales'].add(5)
        self.assertEqual(result['ibos_current_day_pivot_breaks'][0]['scales'], [2])


if __name__ == '__main__':
    unittest.main()
