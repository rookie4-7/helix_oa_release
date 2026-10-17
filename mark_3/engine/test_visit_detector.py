from datetime import datetime, timedelta
import unittest

from visit_detector import VisitConfig, describe_visits, track_visits


class VisitTests(unittest.TestCase):
    def setUp(self):
        self.origin = datetime(2023, 1, 1)
        pairs = [(1.2002,1.2),(1.2,1.2012),(1.2012,1.2002),
                 (1.2002,1.20025),(1.20025,1.2012),(1.2012,1.202),
                 (1.202,1.2001),(1.2001,1.2012),(1.2012,1.1995)]
        self.rows = [dict(time=self.origin+timedelta(minutes=15*i),
                          mid_close=c, sell_body_low=min(o,c), buy_body_high=max(o,c),
                          mid_low=min(o,c)-.0002, spread_close=.0001)
                     for i,(o,c) in enumerate(pairs)]
        self.events = [self.event(0,1.2,1,2), self.event(0,1.2,3,3),
                       self.event(2,1.2002,4,2), self.event(3,1.2002,5,3),
                       self.event(5,1.2012,7,2), self.event(6,1.2001,7,2)]
        self.seed = {k:v for k,v in self.events[0].items() if k != 'scale'}
        self.config = VisitConfig()

    def event(self, i, level, known_i, scale):
        time = self.origin+timedelta(minutes=15*i)
        return dict(id=f'Sell_{time.isoformat()}', time=time, level=level,
                    side='Sell', scale=scale,
                    known_at=self.origin+timedelta(minutes=15*(known_i+1)))

    def run_case(self, cutoff=None, rows=None, events=None, config=None):
        return track_visits(rows or self.rows, events or self.events, self.seed,
                            config or self.config, cutoff or self.origin+timedelta(hours=5))

    def test_adjacent_pivots_and_scales_count_one_visit(self):
        result = self.run_case()
        self.assertEqual(len(result['visits']),3)
        self.assertEqual(len(result['visits'][1]['pivot_ids']),2)

    def test_higher_out_of_band_low_is_not_added(self):
        result = self.run_case()
        self.assertNotIn(self.events[4]['id'], [i for v in result['visits'] for i in v['pivot_ids']])

    def test_confirmation_is_required(self):
        delayed = [dict(e,known_at=self.origin+timedelta(days=1)) if e['time']==self.rows[6]['time'] else e for e in self.events]
        self.assertEqual(len(self.run_case(events=delayed)['visits']),2)

    def test_seed_unavailable_before_confirmation(self):
        result = self.run_case(cutoff=self.origin+timedelta(minutes=15))
        self.assertEqual(result['state'],'seed_not_confirmed')

    def test_first_body_close_break_consumes_structure(self):
        result = self.run_case()
        self.assertEqual(result['state'],'broken')
        self.assertEqual(result['break_event']['candle_time'],self.rows[8]['time'])
        extra = self.rows+[dict(self.rows[2],time=self.origin+timedelta(hours=3))]
        self.assertEqual(self.run_case(rows=extra)['visits'],result['visits'])

    def test_close_equal_to_support_is_not_break(self):
        rows = [dict(r) for r in self.rows]
        rows[-1]['mid_close'] = 1.2
        self.assertIsNone(self.run_case(rows=rows)['break_event'])

    def test_wick_does_not_create_body_visit(self):
        rows = [dict(r) for r in self.rows[:6]]
        for r in rows[2:5]:
            r['sell_body_low'] = 1.201
            r['mid_close'] = 1.2012
            r['mid_low'] = 1.2
        self.assertEqual(len(self.run_case(rows=rows)['visits']),1)

    def test_insufficient_departure_does_not_split_visit(self):
        result = self.run_case(config=VisitConfig(departure_pips=15))
        self.assertLess(len(result['visits']),3)

    def test_buy_sell_symmetry(self):
        rows = [dict(r, mid_close=2.4-r['mid_close'],
                     buy_body_high=2.4-r['sell_body_low'],
                     sell_body_low=2.4-r['buy_body_high']) for r in self.rows]
        events = [dict(e, id=e['id'].replace('Sell','Buy'),side='Buy',level=2.4-e['level']) for e in self.events]
        seed = {k:v for k,v in events[0].items() if k!='scale'}
        result = track_visits(rows,events,seed,VisitConfig(side='Buy'),self.origin+timedelta(hours=5))
        original = self.run_case()
        self.assertEqual(len(result['visits']),len(original['visits']))
        self.assertEqual(result['break_event']['candle_time'],original['break_event']['candle_time'])
        self.assertAlmostEqual(result['measurements']['sd_pips'],original['measurements']['sd_pips'])

    def test_prefix_snapshots_exclude_future_confirmations(self):
        for i in range(2,len(self.rows)):
            cutoff = self.rows[i]['time']+timedelta(minutes=15)
            prefix = self.rows[:i+1]
            allowed = [e for e in self.events if e['known_at']<=cutoff]
            self.assertEqual(self.run_case(cutoff=cutoff),self.run_case(cutoff=cutoff,rows=prefix,events=allowed))

    def test_no_five_against_five_ratio_with_three_visits(self):
        stats = self.run_case()['measurements']
        self.assertIsNone(stats['recent_earlier_sd_ratio'])
        self.assertEqual(stats['tightening_status'],'insufficient_visits')
        self.assertFalse(stats['obstacle_exception_applied'])

    def test_empty_statistics_are_defined(self):
        result = describe_visits([],self.config)
        self.assertIsNone(result['sd_pips'])
        self.assertFalse(result['repeated_level_detected'])

    def test_first_visit_count_is_separate_from_later_representative(self):
        result = self.run_case()
        visit = result['visits'][1]
        self.assertLess(visit['first_counted_at'], visit['known_at'])
        self.assertEqual(visit['representative_time'], self.rows[3]['time'])


if __name__=='__main__':
    unittest.main()
