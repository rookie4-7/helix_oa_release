from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo


LONDON = ZoneInfo("Europe/London")
UTC = ZoneInfo("UTC")
ASIA_START = time(0, 0)
ASIA_END = time(7, 44, 59)
PRE_LONDON_STRUCTURE_START = time(7, 45)
PRE_LONDON_STRUCTURE_END = time(8, 0)
LONDON_SETUP_START = time(8, 0)
LONDON_SETUP_END = time(12, 0)
DAILY_SWING_END = time(12, 0)
FORCED_CLOSE_TIME = time(18, 0)


@dataclass(frozen=True)
class SessionFlags:
    london_time: datetime
    london_date: date
    new_london_day: bool
    in_asia: bool
    in_daily_swing: bool
    in_pre_london_structure: bool
    in_london_setup: bool
    asia_start: bool
    london_setup_start: bool


def normalize_utc_naive(value: Any) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = datetime.fromisoformat(str(value))
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.astimezone(UTC).replace(tzinfo=None)


def to_london(value: datetime) -> datetime:
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return timestamp.astimezone(LONDON)


def london_date(value: datetime) -> date:
    return to_london(value).date()


def is_asia_session(value: datetime | time) -> bool:
    current_time = session_time(value)
    return ASIA_START <= current_time <= ASIA_END


def is_daily_swing_session(value: datetime | time) -> bool:
    current_time = session_time(value)
    return current_time < DAILY_SWING_END


def is_pre_london_structure_session(value: datetime | time) -> bool:
    current_time = session_time(value)
    return PRE_LONDON_STRUCTURE_START <= current_time < PRE_LONDON_STRUCTURE_END


def is_london_setup_session(value: datetime | time) -> bool:
    current_time = session_time(value)
    return LONDON_SETUP_START <= current_time < LONDON_SETUP_END


def session_flags(
    london_timestamp: datetime,
    previous_london_date: date | None,
    previous_in_asia: bool,
    previous_in_london_setup: bool,
) -> SessionFlags:
    current_date = london_timestamp.date()
    in_asia = is_asia_session(london_timestamp)
    in_pre_london_structure = is_pre_london_structure_session(london_timestamp)
    in_london_setup = is_london_setup_session(london_timestamp)
    return SessionFlags(
        london_time=london_timestamp,
        london_date=current_date,
        new_london_day=previous_london_date is None or current_date != previous_london_date,
        in_asia=in_asia,
        in_daily_swing=is_daily_swing_session(london_timestamp),
        in_pre_london_structure=in_pre_london_structure,
        in_london_setup=in_london_setup,
        asia_start=in_asia and not previous_in_asia,
        london_setup_start=in_london_setup and not previous_in_london_setup,
    )


def forced_close_utc_naive(entry_time: datetime) -> datetime:
    london_entry = to_london(entry_time)
    london_close = datetime.combine(london_entry.date(), FORCED_CLOSE_TIME, tzinfo=LONDON)
    return london_close.astimezone(UTC).replace(tzinfo=None)


def london_setup_end_utc_naive(entry_line_time: datetime) -> datetime:
    london_entry_line = to_london(entry_line_time)
    london_end = datetime.combine(london_entry_line.date(), LONDON_SETUP_END, tzinfo=LONDON)
    return london_end.astimezone(UTC).replace(tzinfo=None)


def session_time(value: datetime | time) -> time:
    return value.time() if isinstance(value, datetime) else value
