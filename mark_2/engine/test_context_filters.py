from dataclasses import replace
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from config import Mark2Params, validate_params
from context_filters import (apply_context_filters, cluster_windows, expires_at,
                             pivot_zone, rejects_22_only)
from strategy_logic import generate_signals
from test_mark2 import fixture, params, row
from workbook_config import WorkbookConfigError


class ContextFilters(unittest.TestCase):
    def data(self):
        return [row(datetime(2022, 1, 5)+timedelta(minutes=15*i), 1.3000, 1.3002) for i in range(12)]

    def event(self, rows, i=8, anchors=None, side='Buy'):
        return dict(line_version=1, line_time=rows[i]['time'], available_from=rows[i]['time']+timedelta(minutes=15),
            active_until=rows[i]['time']+timedelta(hours=2), direction=side, signal_direction=side,
            run_high=1.3002, run_low=1.3000, entry=1.3, stop_loss=1.299, take_profit=1.302,
            setup_type='DS', signal_text='DS', setup_anchors=anchors or [])

    def signal(self, rows, event):
        return dict(signal_id='s', direction=event['direction'], run_start_time=rows[7]['time'],
                    status='Valid', entry_line_events=[event])

    def zone(self, rows):
        return dict(id='c', kind='cluster', created=5, low=1.2999, high=1.3003,
                    known_at=rows[5]['time']+timedelta(minutes=15), score=60.0)

    def cluster_params(self):
        return replace(Mark2Params(), use_pivot_obstacles=False, reject_22_only_setups=False)

    def check(self, data, event, zone):
        with patch('context_filters.cluster_windows', return_value={zone['created']: zone}):
            return apply_context_filters(data, [self.signal(data, event)], self.cluster_params())[0]

    def test_defaults_are_frozen_no_expiry_and_three_switches_on(self):
        p=validate_params(Mark2Params())
        self.assertTrue(p.use_pivot_obstacles and p.use_active_price_cluster_stop_filter and p.reject_22_only_setups)
        self.assertEqual((p.pivot_obstacle_scale, p.pivot_obstacle_expiry_months, p.price_cluster_expiry_months), (5, 0, 0))

    def test_invalid_parameters(self):
        for changes in ({'pivot_obstacle_scale': 2}, {'price_cluster_expiry_months': -1},
                        {'price_cluster_candles': 1}, {'price_cluster_min_score': 101}):
            with self.assertRaises(WorkbookConfigError): validate_params(replace(Mark2Params(), **changes))

    def test_setup_only_22_is_rejected(self):
        self.assertTrue(rejects_22_only([dict(source='Current_day_pivot', scales=[2])]))

    def test_larger_actual_setup_alternative_preserved(self):
        for scales in ([2, 3], [2, 5]):
            self.assertFalse(rejects_22_only([dict(source='Current_day_pivot', scales=[2]),
                                            dict(source='Current_day_pivot', scales=scales)]))

    def test_independent_asia_preserved(self):
        self.assertFalse(rejects_22_only([dict(source='Current_day_pivot', scales=[2]),
                                        dict(source='Asia_setup', scales=[])]))

    def test_incidental_pivot_is_not_an_alternative(self):
        self.assertTrue(rejects_22_only([dict(source='Current_day_pivot', scales=[2]),
                                       dict(source='Historical_context', scales=[5])]))

    def test_wick_does_not_cancel_cluster(self):
        data=self.data(); data[6]['mid_high']=1.305
        s=self.check(data, self.event(data), self.zone(data))
        self.assertEqual(s['status'], 'Invalid')
        self.assertEqual(s['entry_line_events'], [])

    def test_close_beyond_cancels_cluster_even_open_inside(self):
        data=self.data(); data[6]=row(data[6]['time'], 1.3002, 1.3005)
        self.assertEqual(self.check(data, self.event(data), self.zone(data))['status'], 'Valid')

    def test_close_on_boundary_does_not_cancel(self):
        data=self.data(); data[6]=row(data[6]['time'], 1.3002, 1.3003)
        self.assertEqual(self.check(data, self.event(data), self.zone(data))['status'], 'Invalid')

    def test_support_cancellation_is_symmetric(self):
        data=self.data(); data[6]=row(data[6]['time'], 1.3000, 1.2998)
        self.assertEqual(self.check(data, self.event(data, side='Sell'), self.zone(data))['status'], 'Valid')

    def test_new_cluster_cannot_block_existing_run(self):
        data=self.data(); zone=self.zone(data); zone['created']=7
        self.assertEqual(self.check(data, self.event(data), zone)['status'], 'Valid')

    def test_future_close_does_not_cancel_at_signal(self):
        data=self.data(); data[10]=row(data[10]['time'], 1.3000, 1.305)
        self.assertEqual(self.check(data, self.event(data), self.zone(data))['status'], 'Invalid')

    def pivot_check(self, data):
        zone=self.zone(data) | {'kind':'pivot'}
        p=replace(self.cluster_params(),use_pivot_obstacles=True,use_active_price_cluster_stop_filter=False)
        with patch('context_filters.pivot_confirmations',return_value={5:[{'side':'Buy'}]}), \
             patch('context_filters.pivot_zone',return_value=zone):
            return apply_context_filters(data,[self.signal(data,self.event(data))],p)[0]

    def test_pivot_wick_only_does_not_cancel(self):
        data=self.data();data[6]['mid_high']=1.305
        self.assertEqual(self.pivot_check(data)['status'],'Invalid')

    def test_pivot_body_beyond_cancels_even_close_returns_inside(self):
        data=self.data();data[6]=row(data[6]['time'],1.3005,1.3002)
        self.assertEqual(self.pivot_check(data)['status'],'Valid')

    def test_same_candle_pivot_confirmation_cannot_block(self):
        data=self.data();zone=self.zone(data) | {'kind':'pivot','created':8}
        p=replace(self.cluster_params(),use_pivot_obstacles=True,use_active_price_cluster_stop_filter=False)
        with patch('context_filters.pivot_confirmations',return_value={8:[{'side':'Buy'}]}), \
             patch('context_filters.pivot_zone',return_value=zone):
            s=apply_context_filters(data,[self.signal(data,self.event(data))],p)[0]
        self.assertEqual(s['status'],'Valid')

    def test_old_uncancelled_cluster_has_no_age_limit(self):
        data=self.data();zone=self.zone(data);zone['known_at']=datetime(2010,1,1)
        self.assertEqual(self.check(data,self.event(data),zone)['status'],'Invalid')

    def test_later_asia_does_not_rescue_earlier_22_line(self):
        data=self.data();e=self.event(data,anchors=[dict(source='Current_day_pivot',scales=[2])])
        later=self.event(data,i=9,anchors=e['setup_anchors']+[dict(source='Asia_setup',scales=[])])
        later['line_version']=2;e['active_until']=later['available_from']
        s=self.signal(data,e);s['entry_line_events'].append(later)
        p=replace(self.cluster_params(),use_active_price_cluster_stop_filter=False,reject_22_only_setups=True)
        output=apply_context_filters(data,[s],p)[0]
        self.assertEqual([r['line_version'] for r in output['entry_line_events']],[2])
        self.assertTrue(output['context_filter_audit'][0]['blocked'])
        self.assertEqual(output['execution_start_time'],later['available_from'])

    def test_no_expiry_and_month_end(self):
        self.assertIsNone(expires_at(datetime(2020, 1, 31), 0))
        self.assertEqual(expires_at(datetime(2020, 1, 31), 1), datetime(2020, 2, 29))

    def test_body_box_differs_by_pivot_side(self):
        data=self.data(); data[4]=row(data[4]['time'], 1.301, 1.302)
        data[5]=row(data[5]['time'], 1.302, 1.300)
        res=pivot_zone(data, 9, 5, 'Buy')
        self.assertEqual((res['low'], res['high']), (1.301, 1.302))
        data[4]=row(data[4]['time'], 1.300, 1.299)
        data[5]=row(data[5]['time'], 1.299, 1.302)
        sup=pivot_zone(data, 9, 5, 'Sell')
        self.assertEqual((sup['low'], sup['high']), (1.299, 1.300))

    def test_original_order_lifetimes_preserved(self):
        data=self.data(); event=self.event(data); original_until=event['active_until']
        with patch('context_filters.cluster_windows', return_value={}):
            output=apply_context_filters(data, [self.signal(data,event)], self.cluster_params())
        self.assertEqual(output[0]['entry_line_events'][0]['active_until'], original_until)
        self.assertEqual(event['active_until'], original_until)

    def test_filter_switches_off_preserve_objects(self):
        data=self.data(); signals=[self.signal(data,self.event(data))]
        output=apply_context_filters(data, signals, params())
        self.assertIs(output, signals)

    def test_actual_22_setup_gate_and_off_switch(self):
        data=fixture()
        self.assertEqual(generate_signals(data, replace(params(), reject_22_only_setups=True))[0]['status'], 'Invalid')
        self.assertEqual(generate_signals(data, params())[0]['status'], 'Valid')

    def test_flat_reference_and_gapped_candidates_excluded(self):
        data=[row(datetime(2022,1,5)+timedelta(minutes=15*i),1.3,1.3) for i in range(110)]
        self.assertEqual(cluster_windows(data), {})
        data=self.data(); data[10]['time']+=timedelta(minutes=15); data=data[:11]
        self.assertNotIn(10, cluster_windows(data, candles=3, reference=2, cutoff=0))


if __name__=='__main__': unittest.main()
