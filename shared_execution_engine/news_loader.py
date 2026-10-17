from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from openpyxl import load_workbook

try:
    from .market_sessions import to_london
except ImportError:
    from market_sessions import to_london


SUPPORTED_NEWS_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xlsm"}
DEFAULT_NEWS_DIRS = (
    "news",
    "calendar",
    "data/news",
    "data/calendar",
    "news_calendar",
)
DEFAULT_NEWS_FILES = (
    "news_calendar.csv",
    "news_calendar.xlsx",
    "news_calendar_2015_2025_clean.csv",
    "news_calendar_2015_2025_clean.xlsx",
    "economic_calendar.csv",
    "economic_calendar.xlsx",
    "forex_factory_calendar.csv",
    "forex_factory_calendar.xlsx",
    "financialjuice_calendar.csv",
    "financialjuice_calendar.xlsx",
)

DATETIME_ALIASES = (
    "datetime",
    "date_time",
    "timestamp",
    "time_utc",
    "event_time",
    "event_datetime",
)
DATE_ALIASES = ("date", "event_date", "calendar_date")
TIME_ALIASES = ("time", "event_time_of_day", "release_time")
TIMEZONE_ALIASES = ("timezone", "tz", "time_zone")
CURRENCY_ALIASES = ("currency", "ccy", "country", "economy")
IMPACT_ALIASES = ("impact", "importance", "priority", "volatility")
TITLE_ALIASES = ("event", "title", "name", "indicator", "description")
ACTUAL_ALIASES = ("actual",)
FORECAST_ALIASES = ("forecast", "consensus")
PREVIOUS_ALIASES = ("previous", "prior")
SOURCE_ALIASES = ("source", "provider")
EVENT_ID_ALIASES = ("event_id", "id")


class NewsDataError(Exception):
    """Raised when a news file exists but cannot be parsed safely."""


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    time_utc: datetime
    time_london: datetime
    currency: str
    impact: str
    title: str
    source: str
    actual: Any = None
    forecast: Any = None
    previous: Any = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class NewsFileStats:
    path: Path
    exists: bool
    rows: int
    parsed_events: int
    skipped_rows: int
    start_time: datetime | None
    end_time: datetime | None
    currencies: list[str]
    impacts: list[str]
    status: str


@dataclass(frozen=True)
class NewsFilterConfig:
    currencies: tuple[str, ...] = ("GBP", "USD")
    impacts: tuple[str, ...] = ("High",)
    minutes_before: int = 30
    minutes_after: int = 30
    source_timezone: str = "UTC"


def discover_news_files(project_root: Path, paths: list[str | Path] | None = None) -> list[Path]:
    root = Path(project_root).expanduser().resolve()
    if paths:
        return _unique_paths(_resolve_path(root, item) for item in paths)

    candidates: list[Path] = []
    for file_name in DEFAULT_NEWS_FILES:
        candidates.append(root / file_name)

    for dir_name in DEFAULT_NEWS_DIRS:
        folder = root / dir_name
        if not folder.exists() or not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_NEWS_SUFFIXES:
                candidates.append(path)

    return _unique_paths(path for path in candidates if path.exists())


def load_news_events(
    project_root: Path,
    start: Any | None = None,
    end: Any | None = None,
    currencies: list[str] | tuple[str, ...] | None = None,
    impacts: list[str] | tuple[str, ...] | None = None,
    paths: list[str | Path] | None = None,
    source_timezone: str = "UTC",
) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for path in discover_news_files(project_root, paths=paths):
        events.extend(read_news_file(path, source_timezone=source_timezone))
    return filter_news_events(events, start=start, end=end, currencies=currencies, impacts=impacts)


def inspect_news_files(
    project_root: Path,
    paths: list[str | Path] | None = None,
    source_timezone: str = "UTC",
) -> list[NewsFileStats]:
    discovered = discover_news_files(project_root, paths=paths)
    if paths and not discovered:
        discovered = [_resolve_path(Path(project_root).expanduser().resolve(), item) for item in paths]

    stats: list[NewsFileStats] = []
    for path in discovered:
        if not path.exists():
            stats.append(
                NewsFileStats(
                    path=path,
                    exists=False,
                    rows=0,
                    parsed_events=0,
                    skipped_rows=0,
                    start_time=None,
                    end_time=None,
                    currencies=[],
                    impacts=[],
                    status="Missing",
                )
            )
            continue

        raw_rows = read_news_rows(path)
        events = _parse_news_rows(raw_rows, path, source_timezone=source_timezone)
        times = [event.time_utc for event in events]
        stats.append(
            NewsFileStats(
                path=path,
                exists=True,
                rows=len(raw_rows),
                parsed_events=len(events),
                skipped_rows=max(0, len(raw_rows) - len(events)),
                start_time=min(times) if times else None,
                end_time=max(times) if times else None,
                currencies=sorted({event.currency for event in events}),
                impacts=sorted({event.impact for event in events}),
                status="Validated" if events else "No Events",
            )
        )
    return stats


def read_news_file(path: str | Path, source_timezone: str = "UTC") -> list[NewsEvent]:
    news_path = Path(path).expanduser().resolve()
    if not news_path.exists():
        raise NewsDataError(f"News file not found: {news_path}")

    return _parse_news_rows(read_news_rows(news_path), news_path, source_timezone=source_timezone)


def read_news_rows(path: str | Path) -> list[dict[str, Any]]:
    news_path = Path(path).expanduser().resolve()
    suffix = news_path.suffix.lower()
    if suffix == ".csv":
        return _read_delimited_news_rows(news_path, delimiter=",")
    if suffix == ".tsv":
        return _read_delimited_news_rows(news_path, delimiter="\t")
    if suffix in {".xlsx", ".xlsm"}:
        return _read_excel_news_rows(news_path)
    raise NewsDataError(f"Unsupported news file type: {news_path.suffix}")


def filter_news_events(
    events: list[NewsEvent],
    start: Any | None = None,
    end: Any | None = None,
    currencies: list[str] | tuple[str, ...] | None = None,
    impacts: list[str] | tuple[str, ...] | None = None,
) -> list[NewsEvent]:
    start_utc = _coerce_to_utc_naive(start, source_timezone="UTC") if start is not None else None
    end_utc = _coerce_to_utc_naive(end, source_timezone="UTC") if end is not None else None
    wanted_currencies = _normalise_filter_values(currencies, normalise_currency)
    wanted_impacts = _normalise_filter_values(impacts, normalise_impact)

    filtered = []
    for event in events:
        if start_utc is not None and event.time_utc < start_utc:
            continue
        if end_utc is not None and event.time_utc > end_utc:
            continue
        if wanted_currencies and event.currency not in wanted_currencies:
            continue
        if wanted_impacts and event.impact not in wanted_impacts:
            continue
        filtered.append(event)

    return sorted(filtered, key=lambda item: item.time_utc)


def news_blackout_events(
    timestamp: Any,
    events: list[NewsEvent],
    config: NewsFilterConfig | None = None,
) -> list[NewsEvent]:
    cfg = config or NewsFilterConfig()
    timestamp_utc = _coerce_to_utc_naive(timestamp, source_timezone=cfg.source_timezone)
    before = timedelta(minutes=cfg.minutes_before)
    after = timedelta(minutes=cfg.minutes_after)
    filtered = filter_news_events(events, currencies=cfg.currencies, impacts=cfg.impacts)

    return [
        event
        for event in filtered
        if event.time_utc - before <= timestamp_utc <= event.time_utc + after
    ]


def is_in_news_blackout(
    timestamp: Any,
    events: list[NewsEvent],
    config: NewsFilterConfig | None = None,
) -> bool:
    return bool(news_blackout_events(timestamp, events, config=config))


def next_news_event(
    timestamp: Any,
    events: list[NewsEvent],
    config: NewsFilterConfig | None = None,
) -> NewsEvent | None:
    cfg = config or NewsFilterConfig()
    timestamp_utc = _coerce_to_utc_naive(timestamp, source_timezone=cfg.source_timezone)
    filtered = filter_news_events(events, currencies=cfg.currencies, impacts=cfg.impacts)
    for event in filtered:
        if event.time_utc >= timestamp_utc:
            return event
    return None


def previous_news_event(
    timestamp: Any,
    events: list[NewsEvent],
    config: NewsFilterConfig | None = None,
) -> NewsEvent | None:
    cfg = config or NewsFilterConfig()
    timestamp_utc = _coerce_to_utc_naive(timestamp, source_timezone=cfg.source_timezone)
    filtered = filter_news_events(events, currencies=cfg.currencies, impacts=cfg.impacts)
    previous = None
    for event in filtered:
        if event.time_utc > timestamp_utc:
            return previous
        previous = event
    return previous


def news_stats_to_manifest_item(stats: NewsFileStats, project_root: Path) -> dict[str, Any]:
    return {
        "data_id": f"NEWS_{stats.path.stem}",
        "data_type": "News_Calendar",
        "file_path": _relative_or_absolute(stats.path, project_root),
        "resolved_path": str(stats.path),
        "file_format": stats.path.suffix.lower().lstrip("."),
        "rows": stats.rows,
        "parsed_events": stats.parsed_events,
        "skipped_rows": stats.skipped_rows,
        "start_date": stats.start_time,
        "end_date": stats.end_time,
        "currencies": stats.currencies,
        "impacts": stats.impacts,
        "status": stats.status,
        "exists": stats.exists,
        "size_bytes": stats.path.stat().st_size if stats.exists and stats.path.exists() else None,
    }


def event_to_record(event: NewsEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "time_utc": event.time_utc,
        "time_london": event.time_london,
        "currency": event.currency,
        "impact": event.impact,
        "title": event.title,
        "source": event.source,
        "actual": event.actual,
        "forecast": event.forecast,
        "previous": event.previous,
    }


def normalise_currency(value: Any) -> str:
    text = str(value or "").strip().upper()
    mapping = {
        "UNITED KINGDOM": "GBP",
        "UK": "GBP",
        "GREAT BRITAIN": "GBP",
        "BRITAIN": "GBP",
        "POUND": "GBP",
        "UNITED STATES": "USD",
        "US": "USD",
        "USA": "USD",
        "DOLLAR": "USD",
    }
    return mapping.get(text, text)


def normalise_impact(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "high impact", "red", "3", "3 stars", "★★★"}:
        return "High"
    if text in {"medium", "med", "medium impact", "orange", "2", "2 stars", "★★"}:
        return "Medium"
    if text in {"low", "low impact", "yellow", "1", "1 star", "★"}:
        return "Low"
    if not text:
        return "Unknown"
    return text.title()


def _parse_news_rows(rows: list[dict[str, Any]], path: Path, source_timezone: str) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for row_idx, raw_row in enumerate(rows, start=2):
        row = _normalise_row_keys(raw_row)
        timestamp = _event_timestamp(row, source_timezone=source_timezone)
        if timestamp is None:
            continue

        currency = normalise_currency(_first_value(row, CURRENCY_ALIASES))
        impact = normalise_impact(_first_value(row, IMPACT_ALIASES))
        title = str(_first_value(row, TITLE_ALIASES) or "").strip()
        if not currency or not title:
            continue

        source = str(_first_value(row, SOURCE_ALIASES) or path.stem).strip()
        event_id = str(_first_value(row, EVENT_ID_ALIASES) or "").strip()
        if not event_id:
            event_id = f"{path.stem}_{row_idx}_{currency}_{timestamp:%Y%m%d%H%M}"

        events.append(
            NewsEvent(
                event_id=event_id,
                time_utc=timestamp,
                time_london=to_london(timestamp),
                currency=currency,
                impact=impact,
                title=title,
                source=source,
                actual=_first_value(row, ACTUAL_ALIASES),
                forecast=_first_value(row, FORECAST_ALIASES),
                previous=_first_value(row, PREVIOUS_ALIASES),
                raw=raw_row,
            )
        )

    return sorted(events, key=lambda item: item.time_utc)


def _event_timestamp(row: dict[str, Any], source_timezone: str) -> datetime | None:
    row_timezone = _first_value(row, TIMEZONE_ALIASES) or source_timezone
    combined = _first_value(row, DATETIME_ALIASES)
    timestamp = _coerce_to_utc_naive(combined, source_timezone=str(row_timezone)) if combined else None
    if timestamp is not None:
        return timestamp

    date_value = _first_value(row, DATE_ALIASES)
    time_value = _first_value(row, TIME_ALIASES)
    if date_value in (None, "") or time_value in (None, ""):
        return None
    local_date = _coerce_date(date_value)
    local_time = _coerce_time(time_value)
    if local_date is None or local_time is None:
        return None
    return _localise_to_utc_naive(datetime.combine(local_date, local_time), str(row_timezone))


def _coerce_to_utc_naive(value: Any, source_timezone: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    elif isinstance(value, str):
        dt = _parse_datetime_text(value)
        if dt is None:
            return None
    else:
        return None
    return _localise_to_utc_naive(dt, source_timezone)


def _localise_to_utc_naive(dt: datetime, source_timezone: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_timezone_from_text(source_timezone))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime_text(value: str) -> datetime | None:
    text = value.strip()
    if not text or text.lower() in {"all day", "tentative", "na", "n/a"}:
        return None
    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text)
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
        "%b %d %Y %H:%M",
        "%B %d %Y %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = _parse_datetime_text(value)
        return parsed.date() if parsed else None
    return None


def _coerce_time(value: Any) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"all day", "tentative", "na", "n/a"}:
            return None
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
    return None


def _timezone_from_text(value: str) -> timezone | ZoneInfo:
    text = str(value or "UTC").strip()
    aliases = {
        "": "UTC",
        "utc": "UTC",
        "gmt": "UTC",
        "london": "Europe/London",
        "uk": "Europe/London",
        "bst": "Europe/London",
        "new york": "America/New_York",
        "ny": "America/New_York",
        "est": "America/New_York",
        "edt": "America/New_York",
    }
    zone_name = aliases.get(text.lower(), text)
    if zone_name == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _read_delimited_news_rows(path: Path, delimiter: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            return []
        return [dict(row) for row in reader if any(value not in (None, "") for value in row.values())]


def _read_excel_news_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            raw_rows = list(sheet.iter_rows(values_only=True))
            header_idx = _find_news_header_row(raw_rows)
            if header_idx is None:
                continue
            headers = [str(value).strip() if value is not None else "" for value in raw_rows[header_idx]]
            if not any(headers):
                continue
            for values in raw_rows[header_idx + 1:]:
                row = dict(zip(headers, values))
                if any(value not in (None, "") for value in row.values()):
                    row["_sheet"] = sheet.title
                    rows.append(row)
    finally:
        workbook.close()
    return rows


def _find_news_header_row(rows: list[tuple[Any, ...]], max_scan_rows: int = 20) -> int | None:
    best_idx = None
    best_score = 0
    for idx, values in enumerate(rows[:max_scan_rows]):
        headers = {_normalise_key(value) for value in values if value not in (None, "")}
        score = _header_match_score(headers)
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx if best_score >= 3 else None


def _header_match_score(headers: set[str]) -> int:
    groups = (
        DATETIME_ALIASES,
        DATE_ALIASES,
        TIME_ALIASES,
        CURRENCY_ALIASES,
        IMPACT_ALIASES,
        TITLE_ALIASES,
    )
    score = 0
    for aliases in groups:
        if any(_normalise_key(alias) in headers for alias in aliases):
            score += 1
    return score


def _normalise_row_keys(row: dict[str, Any]) -> dict[str, Any]:
    return {_normalise_key(key): value for key, value in row.items()}


def _normalise_key(value: Any) -> str:
    return "".join(char for char in str(value or "").strip().lower() if char.isalnum())


def _first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = row.get(_normalise_key(alias))
        if value not in (None, ""):
            return value
    return None


def _normalise_filter_values(
    values: list[str] | tuple[str, ...] | None,
    normaliser: Any,
) -> set[str]:
    if not values:
        return set()
    return {normaliser(value) for value in values if str(value or "").strip()}


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _unique_paths(paths: Any) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return sorted(unique)


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
