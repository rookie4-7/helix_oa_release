from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from config import Mark3Params
from context_filters import apply_context_filters, pivot_zone
from pivot_logic import PivotBook, pivot_audit, pivot_confirmations
from repeated_visit_logic import confirmation_records
from test_mark2 import row


def turn(side='Buy'):
    start = datetime(2023, 1, 11, 6)
    pairs = [(1.3000, 1.3002)] * 16
    pairs[5:7] = [(1.3002, 1.3020), (1.3020, 1.3001)]
    if side == 'Sell':
        pairs = [(2.6-o, 2.6-c) for o, c in pairs]
    return [row(start+timedelta(minutes=15*i), o, c) for i, (o, c) in enumerate(pairs)]


def selected(rows, side='Buy', scales=(2, 3, 5)):
    level = rows[5]['buy_body_high' if side == 'Buy' else 'sell_body_low']
    return [p for events in pivot_confirmations(rows, scales).values() for p in events
            if p['side'] == side and abs(p['level']-level) < 1e-12]


class PivotTurnMerge(unittest.TestCase):
    def test_bullish_bearish_turn_uses_first_candle_once_per_scale(self):
        data = turn()
        pivots = selected(data)
        self.assertEqual(len(pivots), 3)
        self.assertEqual({p['formed_i'] for p in pivots}, {5})
        self.assertEqual({p['formed_time'] for p in pivots}, {data[5]['time']})
        self.assertEqual({p['id'] for p in pivots}, {f"Buy_{data[5]['time'].isoformat()}"})
        self.assertEqual({(p['scale'], p['confirmed_i']) for p in pivots}, {(2, 7), (3, 8), (5, 10)})

    def test_bearish_bullish_support_is_symmetric(self):
        data = turn('Sell')
        pivots = selected(data, 'Sell')
        self.assertEqual(len(pivots), 3)
        self.assertEqual({p['formed_i'] for p in pivots}, {5})

    def test_second_candle_larger_scale_keeps_later_confirmation(self):
        data = turn()
        data[1] = row(data[1]['time'], 1.3030, 1.3000)
        data[4] = row(data[4]['time'], 1.3002, 1.3020)
        data[5] = row(data[5]['time'], 1.3020, 1.3001)
        data[6] = row(data[6]['time'], 1.3000, 1.3002)
        pivots = [p for es in pivot_confirmations(data, (2, 3)).values() for p in es
                  if p['side'] == 'Buy' and p['level'] == 1.3020]
        larger = next(p for p in pivots if p['scale'] == 3)
        self.assertEqual(larger['formed_i'], 4)
        self.assertEqual(larger['confirmation_center_i'], 5)
        self.assertEqual(larger['confirmed_i'], 8)
        self.assertNotEqual(larger['confirmed_i'], larger['formed_i']+3)
        book = PivotBook(1024)
        for i, es in sorted(pivot_confirmations(data, (2, 3)).items()):
            book.confirm(es, i)
        pivot = book.records[larger['id']]
        self.assertEqual(pivot['scale_confirmed_i'], {2: 6, 3: 8})
        records = [p for p in confirmation_records(data, (2, 3)) if p['id'] == larger['id']]
        self.assertEqual(next(p['known_at'] for p in records if p['scale'] == 3),
                         data[8]['time']+timedelta(minutes=15))

    def test_separate_returns_to_same_price_remain_separate(self):
        data = turn()
        data[11] = row(data[11]['time'], 1.3002, 1.3020)
        data[12] = row(data[12]['time'], 1.3020, 1.3001)
        self.assertEqual({p['formed_i'] for p in selected(data, scales=(2,))}, {5, 11})

    def test_equal_extremes_without_shared_close_open_are_not_merged(self):
        data = turn()
        data[6] = row(data[6]['time'], 1.3009, 1.3020)
        self.assertEqual({p['formed_i'] for p in selected(data, scales=(2,))}, {5, 6})

    def test_price_gap_at_the_turn_is_not_merged(self):
        data = turn()
        data[6] = row(data[6]['time'], 1.30201, 1.3001)
        ids = {p['formed_i'] for es in pivot_confirmations(data, (2,)).values() for p in es
               if p['side'] == 'Buy' and p['formed_i'] in (5, 6)}
        self.assertEqual(ids, {6})

    def test_missing_bar_does_not_merge_adjacent_records(self):
        data = turn()
        for r in data[6:]:
            r['time'] += timedelta(minutes=15)
        self.assertEqual({p['formed_i'] for p in selected(data, scales=(2,))}, {5, 6})

    def test_doji_at_shared_turn_keeps_first_candle(self):
        data = turn()
        data[6] = row(data[6]['time'], 1.3020, 1.3020)
        data[7] = row(data[7]['time'], 1.3020, 1.3001)
        self.assertEqual({p['formed_i'] for p in selected(data)}, {5})
        self.assertEqual(len(selected(data)), 3)

    def test_highs_and_lows_have_separate_identity(self):
        data = turn()
        es = pivot_confirmations(data, (2,))
        book = PivotBook(1024)
        for i, pp in sorted(es.items()):
            book.confirm(pp, i)
        self.assertTrue(any(p['side'] == 'Buy' for p in book.records.values()))
        self.assertTrue(any(p['side'] == 'Sell' for p in book.records.values()))

    def test_first_candle_date_is_preserved_across_midnight(self):
        data = turn()
        start = datetime(2023, 1, 10, 22, 30)
        data = [row(start+timedelta(minutes=15*i), r['mid_open'], r['mid_close'])
                for i, r in enumerate(data)]
        self.assertEqual(selected(data)[0]['day'], datetime(2023, 1, 10).date())
        self.assertEqual(selected(data)[0]['formed_time'], datetime(2023, 1, 10, 23, 45))

    def test_causal_prefix_preserves_confirmed_events(self):
        data = turn()
        full = pivot_confirmations(data, (2, 3, 5))
        for stop in range(1, len(data)+1):
            self.assertEqual(pivot_confirmations(data[:stop], (2, 3, 5)),
                             {i: es for i, es in full.items() if i < stop})

    def test_later_scale_does_not_rearm_or_mutate_old_audit(self):
        data = turn()
        es = pivot_confirmations(data, (2, 3, 5))
        book = PivotBook(1024)
        first = next(p for p in es[7] if p['formed_i'] == 5 and p['side'] == 'Buy')
        book.confirm([first], 7)
        book.records[first['id']]['consumed'] = True
        snapshot = pivot_audit(book.records[first['id']])
        for i in (8, 10):
            book.confirm([p for p in es[i] if p['id'] == first['id']], i)
        self.assertTrue(book.records[first['id']]['consumed'])
        self.assertEqual(snapshot['scales'], [2])
        self.assertEqual(snapshot['scale_confirmed_i'], {2: 7})

    def test_obstacle_id_uses_first_candle_for_later_window(self):
        data = turn()
        a = pivot_zone(data, 10, 5, 'Buy', pivot_i=5)
        b = pivot_zone(data, 11, 5, 'Buy', pivot_i=5)
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(a['pivot_time'], data[5]['time'])
        self.assertEqual(a['pair_first'], data[5]['time'])
        self.assertEqual(a['pair_second'], data[6]['time'])

    def test_second_half_cannot_recreate_cancelled_obstacle(self):
        data = turn()
        data[11] = row(data[11]['time'], 1.3002, 1.3030)
        event = dict(line_version=1, line_time=data[12]['time'],
                     available_from=data[12]['time']+timedelta(minutes=15),
                     active_until=data[-1]['time'], run_high=1.3020, run_low=1.3000,
                     entry=1.301, stop_loss=1.300, take_profit=1.304,
                     setup_type='DS', signal_text='DS', setup_anchors=[])
        signal = dict(signal_id='S', direction='Buy', status='Valid',
                      run_start_time=data[11]['time'], entry_line_events=[event])
        p = replace(Mark3Params(), use_repeated_visit_pivot_exception=False,
                    use_active_price_cluster_stop_filter=False, reject_22_only_setups=False)
        output = apply_context_filters(data, [signal], p)[0]
        self.assertEqual(output['context_filter_audit'][0]['hits'], [])


if __name__ == '__main__':
    unittest.main()
