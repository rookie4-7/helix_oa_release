from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from config import Mark4Params, validate_params
from context_filters import apply_context_filters
from repeated_visit_logic import VisitConfig, VisitIndex
from test_mark2 import row
from workbook_config import WorkbookConfigError


def fixture(side='Sell'):
    start = datetime(2023, 1, 11)
    pairs = [(1.2003, 1.2), (1.2, 1.2012), (1.2012, 1.2015),
             (1.2015, 1.2001), (1.2001, 1.2012), (1.2012, 1.2015),
             (1.2015, 1.2002), (1.2002, 1.2012), (1.2012, 1.2015),
             (1.2015, 1.2016), (1.2016, 1.1995)]
    if side == 'Buy':
        pairs = [(2.4-o, 2.4-c) for o, c in pairs]
    rows = [row(start+timedelta(minutes=15*i), o, c) for i, (o, c) in enumerate(pairs)]
    events = [dict(id=f'{side}_{i}', side=side, time=rows[i]['time'],
                   level=rows[i]['sell_body_low' if side == 'Sell' else 'buy_body_high'],
                   known_at=rows[i+2]['time']+timedelta(minutes=15), scale=2)
              for i in (0, 3, 6)]
    pivot = events[-1]
    event = dict(line_version=1, line_time=rows[-1]['time'],
                 available_from=rows[-1]['time']+timedelta(minutes=15),
                 active_until=start+timedelta(hours=12), entry=1.2,
                 stop_loss=1.201, take_profit=1.197, run_high=1.2016, run_low=1.1995,
                 setup_type='DS', signal_text='DS', signal_direction=side,
                 setup_anchors=[dict(source='Current_day_pivot', level=pivot['level'],
                                     formed_time=pivot['time'], known_at=pivot['known_at'],
                                     break_time=rows[-1]['time'], scales=[2, 3])])
    signal = dict(signal_id='S1', direction=side, run_start_time=rows[-1]['time'],
                  status='Valid', entry_line_events=[event])
    return rows, events, signal, event


class VisitEligibility(unittest.TestCase):
    def qualify(self, side='Sell', config=None):
        r, p, s, e = fixture(side)
        return VisitIndex(r, p, config).qualify(s, e)

    def test_three_departed_confirmed_visits_and_actual_source(self):
        result = self.qualify()
        self.assertTrue(result)
        self.assertEqual(result[0]['completed_visits'], 3)
        self.assertIn(result[0]['setup_pivot_id'], result[0]['visit_pivot_ids'])

    def test_buy_sell_mirror(self):
        sell, buy = self.qualify(), self.qualify('Buy')
        self.assertEqual(len(sell), len(buy))
        self.assertAlmostEqual(sell[0]['visit_sd_pips'], buy[0]['visit_sd_pips'])

    def test_configured_minimum_and_departure(self):
        self.assertEqual(self.qualify(config=VisitConfig(minimum_visits=4)), [])
        self.assertEqual(self.qualify(config=VisitConfig(departure_pips=30)), [])

    def test_prior_break_cannot_be_reused(self):
        r, p, s, e = fixture()
        r[-2]['mid_close'] = 1.199
        self.assertEqual(VisitIndex(r, p).qualify(s, e), [])

    def test_first_break_must_be_in_exact_run(self):
        r, p, s, e = fixture()
        s['run_start_time'] = e['available_from']
        self.assertEqual(VisitIndex(r, p).qualify(s, e), [])

    def test_wick_or_body_open_alone_cannot_break(self):
        r, p, s, e = fixture()
        r[-1].update(mid_close=1.2003, sell_body_low=1.1995)
        self.assertEqual(VisitIndex(r, p).qualify(s, e), [])

    def test_future_confirmation_not_credited(self):
        r, p, s, e = fixture()
        future = dict(p[-1], scale=5, known_at=e['available_from']+timedelta(hours=1))
        self.assertEqual(VisitIndex(r, p+[future]).qualify(s, e)[0]['setup_pivot_scales'], [2])

    def test_incidental_asia_and_historical_sources_not_authorised(self):
        r, p, s, e = fixture()
        for source in ('Asia_setup', 'Historical_context', 'incidental_pivot'):
            e['setup_anchors'][0]['source'] = source
            self.assertEqual(VisitIndex(r, p).qualify(s, e), [])

    def test_ibos_actual_current_day_source_can_qualify(self):
        r, p, s, e = fixture()
        e['setup_anchors'][0]['source'] = 'IBOS_required_current_day_pivot'
        self.assertTrue(VisitIndex(r, p).qualify(s, e))

    def test_causal_prefix_and_future_suffix(self):
        r, p, s, e = fixture()
        full = self.qualify()
        extra = row(e['available_from'], 1.199, 1.3)
        self.assertEqual(VisitIndex(r+[extra], p).qualify(s, e), full)
        for bar in r:
            cutoff = bar['time']+timedelta(minutes=15)
            a = VisitIndex(r, p)
            b = VisitIndex([rr for rr in r if rr['time']+timedelta(minutes=15) <= cutoff],
                           [pp for pp in p if pp['known_at'] <= cutoff])
            if p[0]['known_at'] <= cutoff:
                self.assertEqual(a.snapshot(a.records[p[0]['id']], cutoff),
                                 b.snapshot(b.records[p[0]['id']], cutoff))

    def test_invalid_parameters(self):
        for changes in ({'repeated_visit_minimum_visits': 1},
                        {'repeated_visit_minimum_visits': 2.5},
                        {'repeated_visit_membership_tolerance_pips': -1},
                        {'repeated_visit_departure_pips': float('nan')},
                        {'use_repeated_visit_pivot_exception': 'Yes'}):
            with self.assertRaises(WorkbookConfigError):
                validate_params(replace(Mark4Params(), **changes))


class IntegratedWaiver(unittest.TestCase):
    def apply(self, clusters=False, enabled=True, only22=False, eligible=True):
        r, confirmations, s, e = fixture()
        if only22:
            e['setup_anchors'][0]['scales'] = [2]
        z = dict(id='P', kind='pivot', created=5, low=1.1994, high=1.2017,
                 known_at=r[5]['time']+timedelta(minutes=15))
        c = dict(z, id='C', kind='cluster')
        before = deepcopy((r, s))
        with patch('context_filters.pivot_confirmations', return_value={5:[{'side':'Sell'}]}), \
             patch('context_filters.pivot_zone', return_value=z), \
             patch('context_filters.cluster_windows', return_value={5:c} if clusters else {}), \
             patch('context_filters.confirmation_records', return_value=confirmations), \
             patch('context_filters.VisitIndex.qualify', return_value=[{'witness':True}] if eligible else []):
            result = apply_context_filters(r, [s], replace(Mark4Params(),
                use_repeated_visit_pivot_exception=enabled))[0]
        self.assertEqual((r, s), before)
        return result, e

    def test_pivot_only_hit_waived_with_original_lifetime(self):
        s, e = self.apply()
        self.assertEqual(s['status'], 'Valid')
        self.assertEqual(s['entry_line_events'][0]['active_until'], e['active_until'])
        a = s['context_filter_audit'][0]
        self.assertTrue(a['obstacle_exception_applied'])
        self.assertEqual([z['kind'] for z in a['ignored_obstacles']], ['pivot'])
        self.assertEqual(a['hits'], [])

    def test_cluster_still_blocks_eligible_setup(self):
        s, _ = self.apply(clusters=True)
        self.assertEqual(s['status'], 'Invalid')
        self.assertEqual(s['context_filter_audit'][0]['reasons'], ['cluster'])

    def test_22_only_rejection_still_blocks(self):
        s, _ = self.apply(only22=True)
        self.assertEqual(s['status'], 'Invalid')
        self.assertEqual(s['context_filter_audit'][0]['reasons'], ['2/2-only setup'])

    def test_off_switch_preserves_pivot_obstacle(self):
        s, _ = self.apply(enabled=False)
        self.assertEqual(s['status'], 'Invalid')
        self.assertFalse(s['context_filter_audit'][0]['obstacle_exception_applied'])

    def test_ineligible_setup_keeps_pivot(self):
        s, _ = self.apply(eligible=False)
        self.assertEqual(s['status'], 'Invalid')
        self.assertEqual(s['context_filter_audit'][0]['reasons'], ['pivot'])


if __name__ == '__main__':
    unittest.main()
