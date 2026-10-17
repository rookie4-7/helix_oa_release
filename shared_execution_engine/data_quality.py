from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any

try:
    from .models import PriceFile
    from .models import PriceFileStats
    from .price_data_diagnostics import PriceDiagnostics
except ImportError:
    from models import PriceFile
    from models import PriceFileStats
    from price_data_diagnostics import PriceDiagnostics


REQUIRED_MBA_COLUMNS = (
    "time",
    "mid_open",
    "mid_high",
    "mid_low",
    "mid_close",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
)

OPTIONAL_MBA_COLUMNS = (
    "volume",
    "spread_open",
    "spread_high",
    "spread_low",
    "spread_close",
)


def missing_required_columns(headers: list[str]) -> list[str]:
    return [column for column in REQUIRED_MBA_COLUMNS if column not in headers]


def missing_file_stats(price_file: PriceFile) -> PriceFileStats:
    return PriceFileStats(
        price_file=price_file,
        exists=False,
        headers=[],
        rows=0,
        start_time=None,
        end_time=None,
        missing_required_columns=list(REQUIRED_MBA_COLUMNS),
        duplicate_timestamps=0,
        out_of_order_timestamps=0,
        bad_bid_ask_rows=0,
        negative_spread_rows=0,
        rows_checked=0,
    )


def missing_column_stats(
    price_file: PriceFile,
    headers: list[str],
    rows: int,
    missing: list[str],
) -> PriceFileStats:
    return PriceFileStats(
        price_file=price_file,
        exists=True,
        headers=headers,
        rows=rows,
        start_time=None,
        end_time=None,
        missing_required_columns=missing,
        duplicate_timestamps=0,
        out_of_order_timestamps=0,
        bad_bid_ask_rows=0,
        negative_spread_rows=0,
        rows_checked=0,
    )


def quick_price_stats(
    price_file: PriceFile,
    headers: list[str],
    rows: int,
    start_time: Any,
    end_time: Any,
) -> PriceFileStats:
    return PriceFileStats(
        price_file=price_file,
        exists=True,
        headers=headers,
        rows=rows,
        start_time=start_time,
        end_time=end_time,
        missing_required_columns=[],
        duplicate_timestamps=0,
        out_of_order_timestamps=0,
        bad_bid_ask_rows=0,
        negative_spread_rows=0,
        rows_checked=0,
    )


def scan_price_sheet(
    price_file: PriceFile,
    sheet: Any,
    headers: list[str],
    max_scan_rows: int | None,
) -> PriceFileStats:
    indexes = required_indexes(headers)
    diagnostics = PriceDiagnostics(price_file)
    time_idx = indexes["time"]
    bid_close_idx = indexes["bid_close"]
    ask_close_idx = indexes["ask_close"]
    mid_close_idx = indexes["mid_close"]

    rows = 0
    rows_checked = 0
    start_time = None
    end_time = None
    previous_time = None
    seen_times: set[Any] = set()
    duplicate_timestamps = 0
    out_of_order_timestamps = 0
    bad_bid_ask_rows = 0
    negative_spread_rows = 0

    for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        if not values or all(value in (None, "") for value in values):
            continue

        rows += 1
        timestamp = values[time_idx]
        if start_time is None:
            start_time = timestamp
        end_time = timestamp

        if max_scan_rows is not None and rows_checked >= max_scan_rows:
            continue

        rows_checked += 1
        checked_time = diagnostics.observe(timestamp, values, indexes, row_number)
        bid_close = as_number(values[bid_close_idx])
        ask_close = as_number(values[ask_close_idx])
        mid_close = as_number(values[mid_close_idx])

        if checked_time is not None and checked_time in seen_times:
            duplicate_timestamps += 1
        if checked_time is not None:
            seen_times.add(checked_time)

        if previous_time is not None and checked_time is not None and checked_time < previous_time:
            out_of_order_timestamps += 1
        if checked_time is not None:
            previous_time = checked_time

        bid_ask_bad, spread_bad = check_bid_ask_close(bid_close, ask_close, mid_close)
        bad_bid_ask_rows += int(bid_ask_bad)
        negative_spread_rows += int(spread_bad)

    return PriceFileStats(
        price_file=price_file,
        exists=True,
        headers=headers,
        rows=rows,
        start_time=start_time,
        end_time=end_time,
        missing_required_columns=[],
        duplicate_timestamps=duplicate_timestamps,
        out_of_order_timestamps=out_of_order_timestamps,
        bad_bid_ask_rows=bad_bid_ask_rows,
        negative_spread_rows=negative_spread_rows,
        rows_checked=rows_checked,
        diagnostics=diagnostics.finish(complete=rows > 0 and rows_checked == rows),
    )


def required_indexes(headers: list[str]) -> dict[str, int]:
    missing = missing_required_columns(headers)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    return {column: headers.index(column) for column in REQUIRED_MBA_COLUMNS}


def check_bid_ask_close(
    bid_close: float | None,
    ask_close: float | None,
    mid_close: float | None,
) -> tuple[bool, bool]:
    bad_bid_ask = any(value is None for value in (bid_close, ask_close, mid_close))
    negative_spread = False

    if bid_close is not None and ask_close is not None:
        if bid_close > ask_close:
            bad_bid_ask = True
            negative_spread = True

    if bid_close is not None and ask_close is not None and mid_close is not None:
        lower = min(bid_close, ask_close)
        upper = max(bid_close, ask_close)
        if not lower <= mid_close <= upper:
            bad_bid_ask = True

    return bad_bid_ask, negative_spread


def has_quality_failures(stats: PriceFileStats) -> bool:
    return bool(
        stats.missing_required_columns
        or stats.duplicate_timestamps
        or stats.out_of_order_timestamps
        or stats.bad_bid_ask_rows
        or stats.negative_spread_rows
    )


def quality_status(stats: PriceFileStats) -> str:
    if not stats.exists or has_quality_failures(stats) or not valid_date_bounds(stats):
        return "Failed"
    if not stats.rows_checked:
        return "Headers Checked"
    if stats.rows_checked < stats.rows:
        return "Partially Checked"
    return "Validated"


def valid_date_bounds(stats: PriceFileStats) -> bool:
    start, end = stats.start_time, stats.end_time
    if stats.rows <= 0 or not isinstance(start, (date, datetime)) or not isinstance(end, (date, datetime)):
        return False
    try:
        return start <= end and start.year == end.year == stats.price_file.year
    except TypeError:
        return False


def as_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None

