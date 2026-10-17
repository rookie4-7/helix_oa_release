"""Informational price-file diagnostics. Never changes execution or candle data."""
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)
CALENDAR_FILE = Path(__file__).with_name("price_data_calendar_overrides.json")
CALENDAR_SOURCE = "https://www.oanda.com/us-en/trading/hours-of-operation/"


def utc_timestamp(value):
    """Normalise for diagnostics only; the execution loader is not involved."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None, "invalid"
    if not isinstance(value, datetime):
        return None, "invalid"
    if value.tzinfo is None:
        return value, "naive"
    kind = "explicit_utc" if value.utcoffset() == timedelta(0) else "non_utc_offset"
    return value.astimezone(UTC).replace(tzinfo=None), kind


def regular_fx_minute(utc):
    """Pinned reference schedule, not a claim about historical holiday hours."""
    local = utc.replace(tzinfo=UTC).astimezone(NEW_YORK)
    day, minute = local.weekday(), local.hour * 60 + local.minute
    if day == 5 or (day == 6 and minute < 17 * 60 + 5) or (day == 4 and minute >= 16 * 60 + 59):
        return False
    return not 16 * 60 + 59 <= minute < 17 * 60 + 5


def load_closures(path, symbol):
    payload = json.loads(Path(path).read_text())
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or not isinstance(payload.get("closures"), list)
            or not all(isinstance(row, dict) for row in payload["closures"])):
        raise ValueError("Calendar requires schema_version 1 and a list of closure objects")
    closures = []
    for row in payload["closures"]:
        if row.get("symbol") != symbol:
            continue
        start, start_kind = utc_timestamp(row.get("start_utc"))
        end, end_kind = utc_timestamp(row.get("end_utc"))
        if (start_kind != "explicit_utc" or end_kind != "explicit_utc" or start >= end
                or not row.get("reason") or not row.get("source")):
            raise ValueError("Closure requires ordered UTC bounds, symbol, reason and source")
        closures.append((start, end, row["reason"], row["source"]))
    return closures


def expected_slots(year, minutes, closures=(), now=None):
    """A bar is expected if any minute in its half-open interval is tradable."""
    now = now or datetime.now(UTC)
    now = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    start = datetime(year, 1, 1)
    end = min(datetime(year + 1, 1, 1), now.replace(second=0, microsecond=0))
    end -= timedelta(minutes=end.minute % minutes)
    expected, regular = set(), set()
    cursor = start
    while cursor < end:
        if regular_fx_minute(cursor):
            bucket = cursor.replace(minute=cursor.minute - cursor.minute % minutes)
            regular.add(bucket)
            if not any(low <= cursor < high for low, high, _, _ in closures):
                expected.add(bucket)
        cursor += MINUTE
    return expected, len(regular - expected), start, end


def gap_ranges(missing, minutes, observed):
    step = timedelta(minutes=minutes)
    first = min(observed) if observed else None
    last = max(observed) if observed else None
    result = []
    for timestamp in sorted(missing):
        kind = "leading" if first and timestamp < first else "trailing" if last and timestamp > last else "internal"
        if result and result[-1]["end_utc_exclusive"] == timestamp and result[-1]["location"] == kind:
            result[-1]["end_utc_exclusive"] += step
            result[-1]["bars"] += 1
        else:
            result.append({"start_utc": timestamp, "end_utc_exclusive": timestamp + step,
                           "bars": 1, "location": kind})
    return result


class PriceDiagnostics:
    def __init__(self, price_file, calendar_path=CALENDAR_FILE):
        self.file = price_file
        self.minutes = {"1m": 1, "15m": 15}.get(price_file.timeframe)
        self.calendar_path = calendar_path
        self.times = set()
        self.kinds = {"naive": 0, "explicit_utc": 0, "non_utc_offset": 0, "invalid": 0}
        self.off_grid = 0
        self.outside_week = 0
        self.sunday_boundaries = set()
        self.friday_boundaries = set()
        self.boundary_offsets = set()
        self.time_examples = []
        self.spread_samples = 0
        self.invalid_spread_samples = 0
        self.maximum = None

    def observe(self, raw_timestamp, values, indexes, row_number):
        timestamp, kind = utc_timestamp(raw_timestamp)
        self.kinds[kind] += 1
        issues = []
        if timestamp is None:
            issues.append("invalid timestamp")
        else:
            self.times.add(timestamp)
            if self.minutes and (timestamp.minute % self.minutes or timestamp.second or timestamp.microsecond):
                self.off_grid += 1
                issues.append("off candle grid")
            local = timestamp.replace(tzinfo=UTC).astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            day = local.weekday()
            # Use broad weekly boundaries here, not the narrower maintenance window.
            if day == 5 or (day == 6 and minute < 17 * 60) or (day == 4 and minute >= 17 * 60):
                self.outside_week += 1
                issues.append("outside regular FX week under UTC interpretation")
            if day == 6 and 17 * 60 <= minute < 17 * 60 + 15:
                self.sunday_boundaries.add(local.date())
                self.boundary_offsets.add(local.utcoffset().total_seconds() / 3600)
            if day == 4 and 16 * 60 + 45 <= minute < 17 * 60:
                self.friday_boundaries.add(local.date())
                self.boundary_offsets.add(local.utcoffset().total_seconds() / 3600)
        if kind == "non_utc_offset":
            issues.append("timestamp carries non-UTC offset")
        if issues and len(self.time_examples) < 20:
            self.time_examples.append({"row": row_number, "value": str(raw_timestamp), "issues": issues})

        # High/low quotes need not occur at the same instant. Do not call their
        # difference a peak spread. Use only the candle open/close quote samples.
        for endpoint in ("open", "close"):
            try:
                bid = float(values[indexes[f"bid_{endpoint}"]])
                ask = float(values[indexes[f"ask_{endpoint}"]])
                if not (isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
                    raise ValueError("invalid quote pair")
            except (TypeError, ValueError, IndexError, KeyError):
                self.invalid_spread_samples += 1
                continue
            self.spread_samples += 1
            difference = round(ask - bid, 10)
            if self.maximum is None or difference > self.maximum["price_difference"]:
                self.maximum = {"price_difference": difference, "time_utc": timestamp,
                                "row": row_number, "sample": endpoint, "bid": bid, "ask": ask}
        return timestamp

    def finish(self, complete, now=None):
        warnings = []
        timezone_result = "Inconclusive"
        if self.kinds["invalid"] or self.kinds["non_utc_offset"] or self.off_grid or self.outside_week:
            timezone_result = "No"
            warnings.append("Timestamp/UTC consistency check failed; inspect timezone details")
        elif self.kinds["explicit_utc"] and not self.kinds["naive"]:
            timezone_result = "Yes"
        elif self.kinds["naive"] and not self.kinds["explicit_utc"] and self.sunday_boundaries and self.friday_boundaries:
            timezone_result = "Consistent"
        if timezone_result in {"Consistent", "Inconclusive"}:
            warnings.append("Naive or mixed timestamps: source timezone is not independently verified")
        if not complete and timezone_result != "No":
            timezone_result = "Partial scan"

        pip_size = 0.0001 if self.file.symbol == "GBP_USD" else None
        maximum = dict(self.maximum) if self.maximum else None
        if maximum:
            maximum["pips"] = round(maximum["price_difference"] / pip_size, 6) if pip_size else None
        if self.invalid_spread_samples:
            warnings.append(f"{self.invalid_spread_samples} invalid open/close spread samples")

        gaps = {"status": "Partial scan" if not complete else "Unavailable", "missing_bars": None}
        if complete and self.minutes and self.file.symbol == "GBP_USD":
            try:
                closures = load_closures(self.calendar_path, self.file.symbol)
                expected, excluded, start, end = expected_slots(self.file.year, self.minutes, closures, now)
                observed = {t for t in self.times if start <= t < end}
                missing = expected - observed
                gaps = {"status": "Checked", "missing_bars": len(missing), "expected_bars": len(expected),
                        "observed_expected_bars": len(expected & observed), "scope_start_utc": start,
                        "scope_end_utc_exclusive": end, "override_excluded_bars": excluded,
                        "observed_outside_reference_schedule": len(observed - expected),
                        "gaps": gap_ranges(missing, self.minutes, observed),
                        "calendar_source": CALENDAR_SOURCE,
                        "calendar": "NY Sun 17:05-Fri 16:59; daily 16:59-17:05 break; DST-aware",
                        "closures_applied": [{"start_utc": low, "end_utc": high, "reason": reason, "source": source}
                                             for low, high, reason, source in closures if low < end and high > start],
                        "historical_holiday_calendar_complete": False,
                        "interpretation": "Potential missing candle slots, not proven lost data; holidays/no quotes can explain gaps"}
                if missing:
                    warnings.append(f"{len(missing)} potential missing bars against reference schedule")
                if timezone_result == "No":
                    warnings.append("Missing-bar count is provisional because timestamp checks failed")
            except (OSError, ValueError, TypeError, KeyError) as exc:
                gaps["reason"] = str(exc)
                warnings.append("Missing-bar calendar unavailable: " + str(exc))
        elif complete:
            warnings.append("Missing-bar calendar unsupported for this instrument/timeframe")

        return {"informational_only": True, "complete_scan": complete, "warnings": warnings,
                "missing_bar_check": gaps,
                "spread_check": {"status": ("Checked" if complete else "Partial scan") if self.spread_samples else "Unavailable",
                                 "scope": "Max sampled candle open/close ask-minus-bid, not intrabar tick peak",
                                 "unit": "pips", "pip_size": pip_size, "samples_checked": self.spread_samples,
                                 "invalid_samples": self.invalid_spread_samples, "maximum": maximum},
                "timezone_check": {"status": timezone_result, "expected_timezone": "UTC", "kinds": self.kinds,
                                   "off_grid_rows": self.off_grid, "outside_fx_week_rows": self.outside_week,
                                   "sunday_open_dates": len(self.sunday_boundaries),
                                   "friday_close_dates": len(self.friday_boundaries),
                                   "boundary_ny_offsets_hours": sorted(self.boundary_offsets),
                                   "examples": self.time_examples,
                                   "scope": "UTC offsets, candle grid and DST-aware weekly-boundary consistency; no price/time conversion"}}
