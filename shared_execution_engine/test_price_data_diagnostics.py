"""Synthetic reporting-only cases. No strategy/backtest is executed."""
from datetime import datetime as DT, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import price_data_diagnostics as diagnostics


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m1, _, _, _ = diagnostics.expected_slots(2022, 1)
        cls.m15, _, _, _ = diagnostics.expected_slots(2022, 15)

    def test_weekends_and_dst_open_close(self):
        for stamp, expected in [
            ("2022-01-01T12:00", False), ("2022-01-02T22:04", False),
            ("2022-01-02T22:05", True), ("2022-01-07T21:58", True),
            ("2022-01-07T21:59", False), ("2022-07-03T21:04", False),
            ("2022-07-03T21:05", True), ("2022-07-08T20:58", True),
            ("2022-07-08T20:59", False), ("2022-03-13T21:05", True),
            ("2022-11-06T22:05", True),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(DT.fromisoformat(stamp) in self.m1, expected)

    def test_daily_maintenance_not_counted(self):
        self.assertNotIn(DT(2022, 1, 3, 21, 59), self.m1)
        self.assertNotIn(DT(2022, 1, 3, 22, 4), self.m1)
        self.assertIn(DT(2022, 1, 3, 22, 5), self.m1)

    def test_partly_open_m15_candle_is_expected(self):
        self.assertIn(DT(2022, 1, 2, 22), self.m15)
        self.assertIn(DT(2022, 7, 3, 21), self.m15)
        self.assertIn(DT(2022, 1, 7, 21, 45), self.m15)
        self.assertNotIn(DT(2022, 1, 7, 22), self.m15)

    def test_current_year_does_not_include_unfinished_bar(self):
        expected, _, _, end = diagnostics.expected_slots(2022, 15, now=DT(2022, 1, 3, 8, 7))
        self.assertEqual(end, DT(2022, 1, 3, 8))
        self.assertNotIn(DT(2022, 1, 3, 8), expected)

    def test_closure_requires_whole_bar_to_be_excluded(self):
        closures = [(DT(2022, 1, 3, 8), DT(2022, 1, 3, 8, 20), "test", "test source")]
        expected, excluded, _, _ = diagnostics.expected_slots(2022, 15, closures, DT(2022, 1, 3, 9))
        self.assertNotIn(DT(2022, 1, 3, 8), expected)
        self.assertIn(DT(2022, 1, 3, 8, 15), expected)
        self.assertEqual(excluded, 1)

    def test_gap_ranges_include_missing_day_and_edges(self):
        observed = {DT(2022, 1, 3, 8), DT(2022, 1, 5, 8)}
        missing = {DT(2022, 1, 3, 7, 59), DT(2022, 1, 5, 8, 1)}
        missing.update(t for t in self.m1 if t.date() == DT(2022, 1, 4).date())
        ranges = diagnostics.gap_ranges(missing, 1, observed)
        self.assertEqual(sum(r["bars"] for r in ranges), len(missing))
        self.assertEqual(ranges[0]["location"], "leading")
        self.assertEqual(ranges[-1]["location"], "trailing")
        self.assertTrue(any(r["location"] == "internal" and r["bars"] > 1000 for r in ranges))


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.file = SimpleNamespace(timeframe="1m", symbol="GBP_USD", year=2022)
        self.d = diagnostics.PriceDiagnostics(self.file)
        self.headers = ["bid_open", "ask_open", "bid_close", "ask_close", "bid_high", "ask_high"]
        self.indexes = {v: i for i, v in enumerate(self.headers)}
        self.values = [1.2, 1.2002, 1.2, 1.2003, 1.2, 1.9]
        self.start = DT(2022, 1, 3, 8)
        self.slots = {self.start + timedelta(minutes=i) for i in range(4)}
        self.addCleanup(patch.stopall)
        self.expected = patch.object(diagnostics, "expected_slots", return_value=(
            self.slots, 0, DT(2022, 1, 1), DT(2023, 1, 1))).start()

    def observe(self, stamp=None, values=None):
        return self.d.observe(stamp or self.start, values or self.values, self.indexes, 2)

    def test_spread_pips_open_close_not_highs(self):
        self.observe()
        self.observe(values=[1.2, 1.2005, 1.2, 1.2001, 1.2, 1.9])
        spread = self.d.finish(True)["spread_check"]
        self.assertEqual(spread["maximum"]["pips"], 5.0)
        self.assertEqual(spread["maximum"]["sample"], "open")
        self.assertEqual(spread["samples_checked"], 4)

    def test_invalid_spread_samples_are_not_maxima(self):
        for values in ([1.2, float("nan"), 1.2, 1.1], [None, 1.2, -1, 1.2]):
            self.observe(values=values)
        spread = self.d.finish(True)["spread_check"]
        self.assertIsNone(spread["maximum"])
        self.assertEqual(spread["invalid_samples"], 4)
        self.assertEqual(spread["status"], "Unavailable")

    def test_zero_spread_is_valid(self):
        self.observe(values=[1.2] * 6)
        self.assertEqual(self.d.finish(True)["spread_check"]["maximum"]["pips"], 0)

    def test_missing_slots_deduplicate_observations(self):
        self.observe(self.start + timedelta(minutes=1))
        self.observe(self.start + timedelta(minutes=1))
        gaps = self.d.finish(True)["missing_bar_check"]
        self.assertEqual(gaps["missing_bars"], 3)
        self.assertEqual(gaps["observed_expected_bars"], 1)
        self.assertEqual(sum(g["bars"] for g in gaps["gaps"]), 3)
        self.assertEqual([g["location"] for g in gaps["gaps"]], ["leading", "trailing"])

    def test_partial_scan_does_not_claim_missing_bar_total(self):
        self.observe()
        result = self.d.finish(False)
        self.expected.assert_not_called()
        self.assertIsNone(result["missing_bar_check"]["missing_bars"])
        self.assertEqual(result["spread_check"]["status"], "Partial scan")
        self.assertEqual(result["timezone_check"]["status"], "Partial scan")

    def test_naive_timestamps_without_boundaries_inconclusive(self):
        self.observe()
        self.assertEqual(self.d.finish(True)["timezone_check"]["status"], "Inconclusive")

    def test_naive_utc_consistency_with_both_dst_offsets_not_provenance(self):
        for stamp in (DT(2022, 1, 2, 22, 5), DT(2022, 1, 7, 21, 58),
                      DT(2022, 7, 3, 21, 5), DT(2022, 7, 8, 20, 58)):
            self.observe(stamp)
        result = self.d.finish(True)
        self.assertEqual(result["timezone_check"]["status"], "Consistent")
        self.assertEqual(result["timezone_check"]["boundary_ny_offsets_hours"], [-5, -4])
        self.assertTrue(any("not independently verified" in w for w in result["warnings"]))

    def test_explicit_utc(self):
        self.observe("2022-01-03T08:00:00Z")
        self.assertEqual(self.d.finish(True)["timezone_check"]["status"], "Yes")

    def test_mixed_naive_and_utc_is_inconclusive(self):
        self.observe()
        self.observe("2022-01-03T08:01:00Z")
        self.assertEqual(self.d.finish(True)["timezone_check"]["status"], "Inconclusive")

    def test_non_utc_offset_is_flagged_but_only_diagnostic_time_is_normalised(self):
        original = "2022-01-03T09:00:00+01:00"
        self.assertEqual(self.observe(original), self.start)
        self.assertEqual(self.d.finish(True)["timezone_check"]["status"], "No")
        self.assertEqual(original, "2022-01-03T09:00:00+01:00")

    def test_bad_time_grid_and_weekly_boundary_are_flagged(self):
        for stamp in ("bad", DT(2022, 1, 8, 1), DT(2022, 1, 3, 8, 0, 1)):
            with self.subTest(stamp=stamp):
                self.d = diagnostics.PriceDiagnostics(self.file)
                self.observe(stamp)
                result = self.d.finish(True)
                self.assertEqual(result["timezone_check"]["status"], "No")
                self.assertTrue(result["timezone_check"]["examples"])
                self.assertTrue(result["informational_only"])

    def test_m15_grid(self):
        self.file.timeframe = "15m"
        self.d = diagnostics.PriceDiagnostics(self.file)
        self.observe(DT(2022, 1, 3, 8, 1))
        self.assertEqual(self.d.finish(True)["timezone_check"]["off_grid_rows"], 1)

    def test_missing_calendar_is_unavailable_not_exception(self):
        self.d.calendar_path = Path("/no-such-calendar.json")
        self.observe()
        result = self.d.finish(True)
        self.assertEqual(result["missing_bar_check"]["status"], "Unavailable")
        self.assertIn("reason", result["missing_bar_check"])

    def test_closure_configuration_requires_source_and_explicit_utc(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "calendar.json"
            row = {"symbol": "GBP_USD", "start_utc": "2022-01-03T08:00:00Z",
                   "end_utc": "2022-01-03T09:00:00Z", "reason": "fixture", "source": "fixture source"}
            path.write_text(json.dumps({"schema_version": 1, "closures": [row]}))
            self.assertEqual(len(diagnostics.load_closures(path, "GBP_USD")), 1)
            for key, value in (("source", ""), ("start_utc", "2022-01-03T08:00:00")):
                bad = dict(row, **{key: value})
                path.write_text(json.dumps({"schema_version": 1, "closures": [bad]}))
                with self.assertRaises(ValueError):
                    diagnostics.load_closures(path, "GBP_USD")

    def test_malformed_calendar_reports_unavailable_without_stopping_execution(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "calendar.json"
            self.d.calendar_path = path
            self.observe()
            for payload in (None, [], {"schema_version": 1, "closures": [None]},
                            {"schema_version": 1, "closures": {}}, {"schema_version": 1}):
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload))
                    result = self.d.finish(True)
                    self.assertEqual(result["missing_bar_check"]["status"], "Unavailable")
                    self.assertTrue(result["informational_only"])


if __name__ == "__main__":
    unittest.main()
