from dataclasses import replace
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from config import Mark4Params, validate_params
from context_filters import apply_context_filters
import trendline_cluster_logic as logic
from test_mark2 import row
from workbook_config import WorkbookConfigError


class ScoredTrendlines(unittest.TestCase):
    def test_defaults_enable_scoring_without_a_regression_parameter(self):
        p = validate_params(Mark4Params())
        self.assertTrue(p.use_trendline_obstacles and p.use_trendline_cluster_score_filter)
        self.assertFalse(any('regression' in name or 'slope' in name for name in vars(p)))

    def test_strict_thresholds_and_missing_values(self):
        p = Mark4Params()
        s = dict(trade_side_oldest_local=70, trade_side_latest_local=65,
                 opposite_side_latest_trailing=50)
        self.assertEqual(logic.score_qualifies(s, p), [])
        self.assertEqual(logic.score_qualifies({}, p), [])
        for key in s:
            self.assertEqual(logic.score_qualifies(s | {key: s[key]+.00001}, p), [key])

    def test_score_cutoffs_validate(self):
        for value in (-1, 101, float('nan'), True):
            with self.assertRaises(WorkbookConfigError):
                validate_params(replace(Mark4Params(), trendline_trade_side_latest_local_min_score=value))

    def line(self, known=None):
        return dict(x1=0, y1=1.3, x2=10, y2=1.3, active=True,
                    confirmed_time=known or datetime(2023, 1, 11, 7))

    def event(self):
        return dict(run_high=1.3001, run_low=1.2999,
                    available_from=datetime(2023, 1, 11, 9))

    def test_score_alone_cannot_block(self):
        decision = logic.evaluate_line(self.event(), 'Buy', 12, {'Buy': [], 'Sell': []},
            Mark4Params(), {'trade_side_latest_local': 100})
        self.assertFalse(decision['blocked'])

    def test_line_without_sufficient_score_cannot_block(self):
        decision = logic.evaluate_line(self.event(), 'Buy', 12,
            {'Buy': [self.line()], 'Sell': []}, Mark4Params())
        self.assertTrue(decision['trendline_hit'])
        self.assertFalse(decision['blocked'])

    def test_line_and_any_score_blocks_without_slopes(self):
        decision = logic.evaluate_line(self.event(), 'Buy', 12,
            {'Buy': [self.line()], 'Sell': []}, Mark4Params(), {'trade_side_latest_local': 66})
        self.assertTrue(decision['blocked'])
        self.assertFalse(decision['regression_gate_used'])

    def test_no_scoring_switch_means_original_lines(self):
        decision = logic.evaluate_line(self.event(), 'Buy', 12,
            {'Buy': [self.line()], 'Sell': []},
            replace(Mark4Params(), use_trendline_cluster_score_filter=False))
        self.assertTrue(decision['blocked'])

    def test_side_specific_lines(self):
        decision = logic.evaluate_line(self.event(), 'Sell', 12,
            {'Buy': [self.line()], 'Sell': []}, Mark4Params(), {'trade_side_latest_local': 100})
        self.assertFalse(decision['blocked'])

    def test_future_line_confirmation_is_rejected(self):
        with self.assertRaises(ValueError):
            logic.evaluate_line(self.event(), 'Buy', 12,
                {'Buy': [self.line(datetime(2023, 1, 11, 10))], 'Sell': []}, Mark4Params())

    def test_body_endpoint_not_wick_selects_hit(self):
        event = self.event() | dict(run_high=1.302, wick_high=1.3001)
        decision = logic.evaluate_line(event, 'Buy', 12,
            {'Buy': [self.line()], 'Sell': []}, Mark4Params(), {'trade_side_latest_local': 100})
        self.assertFalse(decision['blocked'])

    def test_disabling_trendlines_never_calls_the_new_filter(self):
        p = replace(Mark4Params(), use_trendline_obstacles=False, use_pivot_obstacles=False,
            use_active_price_cluster_stop_filter=False, reject_22_only_setups=False)
        signals = [dict(signal_id='x')]
        with patch.object(logic, 'apply_trendline_filter', side_effect=AssertionError('Called')):
            self.assertIs(apply_context_filters([], signals, p), signals)

    def scorer(self):
        obj = logic.PivotScores.__new__(logic.PivotScores)
        start = datetime(2023, 1, 11, 0)
        obj.rows = [row(start+timedelta(minutes=15*i), 1.3, 1.3001) for i in range(16)]
        obj.candles, obj.cache, obj.contexts = 6, {}, {}
        obj.windows = {i: dict(id=str(i), created=i, start=i-5, low=1.3, high=1.3001,
            known_at=obj.rows[i]['time']+logic.BAR, score=80+i,
            overlap=.8, compactness=.8, slowness=.8, back_and_forth=.8) for i in range(5, 15)}
        return obj

    def test_windows_must_be_known_by_pivot_confirmation(self):
        obj = self.scorer()
        p = dict(id='p', formed_i=5, level=1.3001, known_at=obj.rows[8]['time'])
        score = obj.scores(p, obj.rows[10]['time'])
        self.assertEqual(score['local_box']['id'], '7')
        self.assertEqual(score['trailing_box']['id'], '5')

    def test_future_pivots_excluded_and_missing_oldest_not_fabricated(self):
        obj = self.scorer()
        cutoff = obj.rows[10]['time']
        obj.pivots = [dict(id='p', side='Buy', formed_time=obj.rows[5]['time'], formed_i=5,
            level=1.3001, known_at=obj.rows[8]['time']), dict(id='future', side='Buy',
            formed_time=obj.rows[6]['time'], formed_i=6, level=1.3001, known_at=obj.rows[11]['time'])]
        scores, witnesses = obj.context(cutoff, 'Buy')
        self.assertIsNone(scores['trade_side_oldest_local'])
        self.assertIsNotNone(scores['trade_side_latest_local'])
        self.assertEqual([w['pivot_id'] for w in witnesses], ['p'])

    def test_original_body_break_cancels_line(self):
        line = self.line() | {'active': True}
        candles = [row(datetime(2023, 1, 11, 9), 1.3, 1.3003)]
        candle = candles[0] | dict(mid_body_high=1.3003, mid_body_low=1.3)
        logic.legacy.deactivate_trendline_obstacles(candle, 0, [line], [], .0002)
        self.assertFalse(line['active'])


if __name__ == '__main__':
    unittest.main()
